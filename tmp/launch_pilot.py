import os, sys, time
# 双fork守护进程化，完全脱离会话进程树
pid = os.fork()
if pid > 0:
    print(f"launcher parent exit, child={pid}")
    sys.exit(0)
os.setsid()
pid2 = os.fork()
if pid2 > 0:
    sys.exit(0)
os.chdir("/home/z/my-project/PhysicianBench_for_pmc")
with open("tmp/pilot_run.log", "w") as log, open("tmp/pilot_err.log", "w") as err:
    os.dup2(log.fileno(), 1)
    os.dup2(err.fileno(), 2)
os.execvp("python3", ["python3", "-u", "-m", "scripts.generate_oncology_v2", "--pilot", "5"])
