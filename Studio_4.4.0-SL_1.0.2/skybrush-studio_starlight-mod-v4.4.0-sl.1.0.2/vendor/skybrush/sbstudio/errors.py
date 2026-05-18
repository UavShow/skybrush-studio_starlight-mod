__all__ = ("SkybrushStudioError",)


class SkybrushStudioError(RuntimeError):
    

    def format_message(self) -> str:
        
        return str(self)
