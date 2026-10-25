"""Recovered return-to-home steering and frame integration core.

The equations in this module follow the bundled Go helper's recovered
``Boid.behaviors`` and ``Boid.update`` control flow. Blender objects and
keyframes are deliberately handled by the add-on facade, not by this module.
"""

from dataclasses import dataclass, field
import heapq
import math
from mathutils import Vector


_ZERO = Vector((0.0, 0.0, 0.0))
_SQRT3 = 1.732
_ARRIVAL_DISTANCE = 0.1
_ARRIVAL_DISTANCE_SQUARED = _ARRIVAL_DISTANCE * _ARRIVAL_DISTANCE


class _SpatialHash:
    """Dynamic broad phase that keeps exact Boid order for nearby candidates."""

    def __init__(self, states, cell_size):
        self.cell_size = max(float(cell_size), 1.0e-6)
        self.cells = {}
        self.state_cells = {}
        for index, state in enumerate(states):
            state._simulation_index = index
            cell = self._cell(state.position)
            self.state_cells[index] = cell
            self.cells.setdefault(cell, []).append(state)

    def _cell(self, position):
        size = self.cell_size
        return (math.floor(position.x / size),
                math.floor(position.y / size),
                math.floor(position.z / size))

    def move(self, state):
        index = state._simulation_index
        old_cell = self.state_cells[index]
        new_cell = self._cell(state.position)
        if old_cell == new_cell:
            return
        bucket = self.cells[old_cell]
        bucket.remove(state)
        if not bucket:
            del self.cells[old_cell]
        self.cells.setdefault(new_cell, []).append(state)
        self.state_cells[index] = new_cell

    def nearby(self, state, radius, all_states):
        # Avoid a large empty-cube walk when the interaction radius spans most
        # of the scene. This fallback is the original exact scan.
        span = int(math.ceil(max(radius, 0.0) / self.cell_size))
        side = span * 2 + 1
        if side * side * side >= len(all_states):
            return all_states
        cx, cy, cz = self.state_cells[state._simulation_index]
        candidates = []
        for x in range(cx - span, cx + span + 1):
            for y in range(cy - span, cy + span + 1):
                for z in range(cz - span, cz + span + 1):
                    candidates.extend(self.cells.get((x, y, z), ()))
        candidates.sort(key=lambda item: item._simulation_index)
        return candidates


@dataclass(frozen=True)
class FlightLimits:
    """Motion limits used by the legacy Go simulation, in frame units."""

    fps: float
    max_velocity: float
    max_acceleration: float
    min_distance: float
    deaccel_distance: float
    max_horizontal_velocity: float
    max_vertical_up_velocity: float
    max_vertical_down_velocity: float
    max_acceleration_x: float
    max_acceleration_y: float
    max_acceleration_z: float

    @classmethod
    def from_scene_properties(cls, properties, fps: float) -> "FlightLimits":
        fps = max(float(fps), 1.0)
        max_velocity_mps = max(float(properties.max_velocity), 0.0)
        max_acceleration_mps2 = max(
            float(properties.max_x_acceleration),
            float(properties.max_y_acceleration),
            float(properties.max_z_acceleration),
            0.0,
        )
        max_velocity = max_velocity_mps / fps
        max_acceleration = max_acceleration_mps2 / (fps * fps)
        deaccel_distance = (
            max_velocity_mps * max_velocity_mps / max_acceleration_mps2
            if max_acceleration_mps2 > 0.0
            else 0.0
        )
        return cls(
            fps=fps,
            max_velocity=max_velocity,
            max_acceleration=max_acceleration,
            min_distance=max(float(properties.min_distance), 0.0),
            deaccel_distance=deaccel_distance,
            max_horizontal_velocity=max(float(properties.max_horizontal_velocity), 0.0) / fps,
            max_vertical_up_velocity=max(float(properties.max_vertical_up_velocity), 0.0) / fps,
            max_vertical_down_velocity=max(float(properties.max_vertical_down_velocity), 0.0) / fps,
            max_acceleration_x=max(float(properties.max_x_acceleration), 0.0) / (fps * fps),
            max_acceleration_y=max(float(properties.max_y_acceleration), 0.0) / (fps * fps),
            max_acceleration_z=max(float(properties.max_z_acceleration), 0.0) / (fps * fps),
        )


@dataclass
class BoidState:
    """Mutable state for one drone in the legacy sequential simulation."""

    name: str
    position: Vector
    target: Vector
    velocity: Vector = field(default_factory=lambda: Vector(_ZERO))
    acceleration: Vector = field(default_factory=lambda: Vector(_ZERO))
    last_step: Vector = field(default_factory=lambda: Vector(_ZERO))
    max_velocity: float = 0.0
    avoid_collision: bool = True

    @classmethod
    def at(cls, name, position, target, max_velocity, avoid_collision=True):
        return cls(
            name=str(name),
            position=Vector(position),
            target=Vector(target),
            max_velocity=float(max_velocity),
            avoid_collision=bool(avoid_collision),
        )

    def apply_force(self, force) -> None:
        self.acceleration += Vector(force)

    def _separation(self, others, limits: FlightLimits, maximum_effect_distance=None) -> Vector:
        """Accumulate the recovered Go separation response from nearby boids."""
        steer = Vector(_ZERO)
        speed = self.velocity.length

        for other in others:
            if other is self:
                continue

            away = self.position - other.position
            if (
                maximum_effect_distance is not None
                and away.length_squared > (maximum_effect_distance + 1.0e-9) ** 2
            ):
                continue
            distance = away.length
            if distance <= 1.0e-12:
                continue

            cosine = 0.0
            projected_speed = 0.0
            effect_distance = limits.min_distance
            if speed > 0.0:
                cosine = max(-1.0, min(1.0, away.dot(self.velocity) / (distance * speed)))
                if cosine < 0.0:
                    projected_speed = abs(cosine) * speed
                    if self.max_velocity > 0.0 and limits.deaccel_distance > 0.0:
                        ratio = projected_speed / self.max_velocity
                        effect_distance += ratio * ratio * limits.deaccel_distance * _SQRT3

            if distance >= effect_distance:
                continue

            # The legacy routine adds an away direction and a cross-product
            # term. The latter makes crossing paths separate in 3D.
            steer += away / distance
            steer += away.cross(self.velocity)

            if cosine < 0.0:
                steer_length = steer.length
                if steer_length > 1.0e-12:
                    steer += (steer / steer_length) * projected_speed

            # The Go implementation perturbs the exactly anti-parallel case
            # by rotating the away vector and crossing it with velocity. Its
            # matrix calls encode a one-degree tie-break rotation.
            if cosine < -0.99 and speed > 0.0:
                basis = Vector((0.0, 0.0, 1.0))
                perpendicular = away.cross(basis)
                if perpendicular.length <= 1.0e-12:
                    perpendicular = away.cross(Vector((0.0, 1.0, 0.0)))
                if perpendicular.length > 1.0e-12:
                    perpendicular.normalize()
                    steer += perpendicular.cross(self.velocity) * math.sin(math.radians(1.0))

        return steer

    def _seek_arrive(self, limits: FlightLimits) -> Vector:
        toward = self.target - self.position
        distance = toward.length
        if distance <= 1.0e-12 or limits.max_acceleration <= 0.0:
            return Vector(_ZERO)

        desired_speed = self.max_velocity
        if limits.deaccel_distance > 0.0 and distance < limits.deaccel_distance:
            desired_speed *= (distance / limits.deaccel_distance) * _SQRT3

        desired = (toward / distance) * desired_speed
        # The Go helper returns desired_velocity - velocity directly.
        # ``update`` then clamps the sum of all behavior forces to the
        # acceleration limit. Normalizing here changes the arrival profile.
        return desired - self.velocity

    def behaviors(self, others, limits: FlightLimits) -> None:
        if self.avoid_collision:
            self.apply_force(self._separation(others, limits))
        self.apply_force(self._seek_arrive(limits))

    def update(self, others, limits: FlightLimits, maximum_distance=None,
               use_axis_acceleration=False, use_axis_velocity=False) -> None:
        if use_axis_acceleration:
            # Keep the recovered steering direction. Clipping components
            # independently rotates the force and can create a long orbit
            # around an occupied home cell.
            scale = 1.0
            for component, maximum in zip(
                self.acceleration,
                (limits.max_acceleration_x, limits.max_acceleration_y,
                 limits.max_acceleration_z),
            ):
                if abs(component) > maximum:
                    scale = min(scale, maximum / abs(component))
            self.acceleration *= scale
        acceleration_length = self.acceleration.length
        if acceleration_length > limits.max_acceleration and acceleration_length > 0.0:
            self.acceleration *= limits.max_acceleration / acceleration_length

        distance = (self.target - self.position).length
        if distance <= 0.5:
            self.max_velocity = limits.max_velocity
        else:
            if maximum_distance is None:
                maximum_distance = distance
                for other in others:
                    other_distance = (other.target - other.position).length
                    maximum_distance = max(maximum_distance, other_distance)
            self.max_velocity = (
                limits.max_velocity * distance / maximum_distance
                if maximum_distance > 0.0
                else limits.max_velocity
            )

        speed = self.velocity.length
        if speed > self.max_velocity and speed > 0.0:
            self.velocity *= self.max_velocity / speed

        if use_axis_velocity:
            horizontal = math.hypot(self.velocity.x, self.velocity.y)
            if horizontal > limits.max_horizontal_velocity and horizontal > 0.0:
                factor = limits.max_horizontal_velocity / horizontal
                self.velocity.x *= factor
                self.velocity.y *= factor
            vertical_limit = (limits.max_vertical_up_velocity if self.velocity.z >= 0.0
                              else limits.max_vertical_down_velocity)
            self.velocity.z = max(-vertical_limit, min(vertical_limit, self.velocity.z))

        if use_axis_acceleration:
            # The speed cap above can itself alter velocity. Constrain the
            # actual position step against the preceding rendered step too.
            change = self.velocity - self.last_step
            scale = 1.0
            for component, maximum in zip(
                change,
                (limits.max_acceleration_x, limits.max_acceleration_y,
                 limits.max_acceleration_z),
            ):
                if abs(component) > maximum:
                    scale = min(scale, maximum / abs(component))
            if change.length > limits.max_acceleration and change.length > 0.0:
                scale = min(scale, limits.max_acceleration / change.length)
            self.velocity = self.last_step + change * scale

        self.position += self.velocity
        self.last_step = Vector(self.velocity)
        self.velocity += self.acceleration
        self.acceleration = Vector(_ZERO)


class AlgorithmNotReconstructed(NotImplementedError):
    """Raised when scene input cannot be matched to the recovered model."""


def iter_simulate_return(states, limits: FlightLimits, avoid_collision=True, max_steps=10000,
                         start_frame=1, enforce_min_distance=False, chunk_size=32,
                         use_axis_acceleration=True, use_axis_velocity=True):
    """Yield progress while returning one position sequence per state.

    The old helper updates drones in list order, so each later drone in one
    frame observes the already-updated positions of earlier drones. It exits
    only after every drone is within 0.1 scene units of its own target. Yielding
    between small batches lets Blender's modal event loop redraw progress while
    preserving that sequential update order.
    """
    states = list(states)
    if not states:
        raise AlgorithmNotReconstructed("没有可返航的无人机。")

    for state in states:
        state.avoid_collision = bool(avoid_collision)
    tracks = {state.name: [Vector(state.position)] for state in states}
    individually_arrived = {
        state.name: (state.target - state.position).length_squared
        < _ARRIVAL_DISTANCE_SQUARED
        for state in states
    }
    arrived_count = sum(individually_arrived.values())

    # The Go helper scans all boids for separation and for the maximum
    # remaining target distance on every update. A dynamic grid and lazy max
    # heap reduce that work without changing the sequential update semantics.
    max_deaccel_radius = limits.min_distance + limits.deaccel_distance * _SQRT3
    grid = _SpatialHash(states, max(max_deaccel_radius, 1.0))
    versions = [0] * len(states)
    distance_heap = []
    for index, state in enumerate(states):
        distance = (state.target - state.position).length
        heapq.heappush(distance_heap, (-distance, index, versions[index]))

    def current_maximum_distance():
        while distance_heap:
            negative_distance, index, version = distance_heap[0]
            if version == versions[index]:
                return -negative_distance
            heapq.heappop(distance_heap)
        return 0.0

    chunk_size = max(1, int(chunk_size))
    for _frame_offset in range(1, int(max_steps) + 1):
        all_arrived = True
        for state_index, state in enumerate(states):
            if state.avoid_collision:
                speed = state.velocity.length
                radius = limits.min_distance
                if speed > 0.0 and state.max_velocity > 0.0:
                    ratio = speed / state.max_velocity
                    radius += ratio * ratio * limits.deaccel_distance * _SQRT3
                others = grid.nearby(state, radius, states)
                state.apply_force(state._separation(others, limits, radius))
            state.apply_force(state._seek_arrive(limits))

            max_distance = current_maximum_distance()
            previous_position = Vector(state.position)
            state.update(states, limits, maximum_distance=max_distance,
                         use_axis_acceleration=use_axis_acceleration,
                         use_axis_velocity=use_axis_velocity)
            grid.move(state)
            index = state._simulation_index
            versions[index] += 1
            new_distance = (state.target - state.position).length
            heapq.heappush(distance_heap, (-new_distance, index, versions[index]))
            if not individually_arrived[state.name]:
                tracks[state.name].append(Vector(state.position))
                displacement = state.position - previous_position
                can_stop = (not use_axis_acceleration or all(
                    abs(component) <= maximum + 1.0e-8
                    for component, maximum in zip(
                        displacement,
                        (limits.max_acceleration_x, limits.max_acceleration_y,
                         limits.max_acceleration_z),
                    )
                ))
                if new_distance * new_distance < _ARRIVAL_DISTANCE_SQUARED and can_stop:
                    individually_arrived[state.name] = True
                    arrived_count += 1
            if not individually_arrived[state.name]:
                all_arrived = False

            if (state_index + 1) % chunk_size == 0 or state_index + 1 == len(states):
                yield _frame_offset, arrived_count, len(states)

        if all_arrived:
            return tracks

    raise AlgorithmNotReconstructed(
        "返航模拟在 %d 帧内未能让全部无人机进入目标 0.1 米范围；未写入关键帧。"
        % int(max_steps)
    )


def simulate_return(states, limits: FlightLimits, avoid_collision=True, max_steps=10000,
                    start_frame=1, enforce_min_distance=False, progress_callback=None,
                    use_axis_acceleration=True, use_axis_velocity=True, chunk_size=32):
    """Synchronous compatibility wrapper around :func:`iter_simulate_return`."""
    iterator = iter_simulate_return(
        states, limits, avoid_collision=avoid_collision, max_steps=max_steps,
        start_frame=start_frame, enforce_min_distance=enforce_min_distance,
        use_axis_acceleration=use_axis_acceleration,
        use_axis_velocity=use_axis_velocity,
        chunk_size=chunk_size,
    )
    last_callback_frame = None
    while True:
        try:
            frame_offset, _arrived, _total = next(iterator)
            if (
                progress_callback is not None
                and frame_offset % 100 == 0
                and frame_offset != last_callback_frame
            ):
                progress_callback(frame_offset, states)
                last_callback_frame = frame_offset
        except StopIteration as result:
            return result.value
