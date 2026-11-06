"""A ready-made owner with two pets, shared by the demo, the evaluation and the prompt comparison."""

from pawpal_system import Owner, Pet


def sample_owner(available_minutes: int = 120) -> Owner:
    """Return Jordan with Mochi (dog, 3) and Luna (cat, 5) and nothing scheduled yet."""
    owner = Owner(name="Jordan", available_minutes=available_minutes)
    owner.add_pet(Pet(name="Mochi", species="dog", age=3))
    owner.add_pet(Pet(name="Luna", species="cat", age=5))
    return owner
