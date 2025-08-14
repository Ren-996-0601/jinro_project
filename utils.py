def is_werewolf_side(role):
    return role in ["人狼", "人狼(元怪盗)", "狂人", "狂人(元怪盗)"]

def is_villager_side(role):
    return not is_werewolf_side(role)