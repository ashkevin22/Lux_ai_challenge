import numpy as np

b = open('/Users/kevinash/LUXai/expert/agent2.txt', "r").read()
a = open('/Users/kevinash/LUXai/currentSub/agent.txt',"r").read()

a_stats = []
b_stats = []

for l in a.split('\n')[:-1]:
    a_stats.append(int(l))

for l in b.split('\n')[:-1]:
    b_stats.append(int(l))

a_win = 0
b_win = 0
tie = 0

for x in range(0,len(a_stats)):
    a = a_stats[x]
    b = b_stats[x]
    if a > b:
        a_win += 1
    elif b > a:
        b_win += 1
    else:
        tie += 1


print(f"Averages: currentSub: {np.mean(a_stats)} expert: {np.mean(b_stats)}\n")
print(f"Wins: currentSub: {a_win} expert: {b_win} ties: {tie}")