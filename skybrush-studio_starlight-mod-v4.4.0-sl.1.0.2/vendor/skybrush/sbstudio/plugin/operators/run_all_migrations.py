from bpy.types import Context, Operator

from sbstudio.plugin.migrations import (
    get_migration_details,
    is_migration_needed,
    migrate,
)

__all__ = ("RunAllMigrationOperators",)


CONFIRMATION = """
The format of this file needs to be updated to work correctly with
the current version of the Skybrush add-on.

The file will be updated from version {current} to {latest}.

Do you want to proceed?
"""


class RunAllMigrationOperators(Operator):
    

    bl_idname = "skybrush.run_all_migrations"
    bl_label = "Update to Latest File Format"
    bl_description = "Updates the format of the current file to the latest version"

    @classmethod
    def poll(self, context: Context) -> bool:
        return is_migration_needed(context)

    def invoke(self, context: Context, event):
        if is_migration_needed(context, strict=True):
            
            _, current, latest = get_migration_details(context)
            return context.window_manager.invoke_confirm(
                self,
                event,
                title=self.bl_label,
                message=CONFIRMATION.format(current=current, latest=latest),
            )
        else:
            
            
            
            return self.execute(context)

    def execute(self, context: Context):
        migrate(context)
        return {"FINISHED"}
