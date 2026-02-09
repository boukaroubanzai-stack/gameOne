from settings import STARTING_RESOURCES


class ResourceManager:
    def __init__(self):
        self.amount = STARTING_RESOURCES

    def can_afford(self, cost):
        return self.amount >= cost

    def spend(self, cost):
        if self.can_afford(cost):
            self.amount -= cost
            return True
        return False

    def deposit(self, amount):
        self.amount += amount
