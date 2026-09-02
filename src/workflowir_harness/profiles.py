from enum import Enum


class AssuranceProfile(str, Enum):
    DIRECT = "direct"
    STAGED = "staged"
    GUARDED = "guarded"
    ADAPTIVE = "adaptive"

    @property
    def uses_stages(self) -> bool:
        return self is not AssuranceProfile.DIRECT

    @property
    def allows_repair(self) -> bool:
        return self in {AssuranceProfile.GUARDED, AssuranceProfile.ADAPTIVE}

    @property
    def uses_experience(self) -> bool:
        return self is AssuranceProfile.ADAPTIVE
