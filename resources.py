"""Resource manager: tracks and manages a team's mineral resource balance."""

from settings import STARTING_RESOURCES


class ResourceManager:
    """Tracks a single team's mineral balance (player or AI)."""

    def __init__(self):
        self.amount = STARTING_RESOURCES

    def can_afford(self, cost):
        """Return True if the current balance covers *cost*."""
        return self.amount >= cost

    def spend(self, cost):
        """Deduct *cost* if affordable. Returns True on success."""
        if self.can_afford(cost):
            self.amount -= cost
            return True
        return False

    def deposit(self, amount):
        """Add *amount* to the balance (e.g. worker delivery)."""
        self.amount += amount
