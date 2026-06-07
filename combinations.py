import itertools

def find_combinations(n, k):
    combinations = list(itertools.combinations(range(1, k + 1), n))
    return combinations

combo = find_combinations(2, 3)
print(combo)