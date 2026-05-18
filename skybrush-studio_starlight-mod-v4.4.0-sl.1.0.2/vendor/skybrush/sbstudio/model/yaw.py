from collections.abc import Sequence
from dataclasses import dataclass
from operator import attrgetter
from typing import Self

__all__ = (
    "YawSetpointList",
    "YawSetpoint",
)


@dataclass
class YawSetpoint:
    

    time: float
    """The timestamp associated to the yaw setpoint, in seconds."""

    angle: float
    """The yaw angle associated to the yaw setpoint, in degrees, CW."""


class YawSetpointList:
    

    def __init__(self, setpoints: Sequence[YawSetpoint] = []):
        self.setpoints = sorted(setpoints, key=attrgetter("time"))

    def append(self, setpoint: YawSetpoint) -> None:
        
        if self.setpoints and self.setpoints[-1].time >= setpoint.time:
            raise ValueError("New setpoint must come after existing setpoints in time")
        self.setpoints.append(setpoint)

    def as_dict(self, ndigits: int = 3):
        
        return {
            "setpoints": [
                [
                    round(setpoint.time, ndigits=ndigits),
                    round(setpoint.angle, ndigits=ndigits),
                ]
                for setpoint in self.setpoints
            ],
            "version": 1,
        }

    def shift_in_place(self, delta: float) -> Self:
        
        for setpoint in self.setpoints:
            setpoint.angle += delta
        return self

    def shift_time_in_place(self, delta: float) -> Self:
        
        for setpoint in self.setpoints:
            setpoint.time += delta
        return self

    def simplify(self) -> Self:
        
        if not self.setpoints:
            return self

        
        angle = self.setpoints[0].angle % 360
        delta = angle - self.setpoints[0].angle
        if delta:
            self.shift_in_place(delta)

        
        new_setpoints: list[YawSetpoint] = []
        last_angular_speed = -1e12
        for setpoint in self.setpoints:
            if not new_setpoints:
                new_setpoints.append(setpoint)
            else:
                dt = setpoint.time - new_setpoints[-1].time
                if dt <= 0:
                    raise RuntimeError(
                        f"Yaw timestamps are not causal ({setpoint.time} <= {new_setpoints[-1].time})"
                    )
                
                
                angular_speed = (
                    round(setpoint.angle, ndigits=3)
                    - round(new_setpoints[-1].angle, ndigits=3)
                ) / round(dt, ndigits=3)
                if abs(angular_speed - last_angular_speed) < 1e-6:
                    new_setpoints[-1] = setpoint
                else:
                    new_setpoints.append(setpoint)
                last_angular_speed = angular_speed

        self.setpoints = new_setpoints

        return self

    def unwrap(self, *, threshold: float = 180, full_cycle: float = 360) -> Self:
        
        for prev, curr in zip(self.setpoints, self.setpoints[1:]):
            diff = curr.angle - prev.angle
            if diff > threshold or diff < -threshold:
                num_cycles = -round(diff / full_cycle)
                curr.angle += num_cycles * full_cycle

        return self
