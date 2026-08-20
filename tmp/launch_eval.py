import os, sys
pid = os.fork()
if pid > 0:
    print(f"eval launcher, child={pid}"); sys.exit(0)
os.setsid()
pid2 = os.fork()
if pid2 > 0:
    sys.exit(0)
os.chdir("/home/z/my-project/PhysicianBench_for_pmc")
with open("tmp/eval_run.log", "w") as log, open("tmp/eval_err.log", "w") as err:
    os.dup2(log.fileno(), 1); os.dup2(err.fileno(), 2)
os.execvp("python3", ["python3", "-u", "-m", "eval.runner",
    "--task-dir", "tasks/oncology-v2/00151e6a402f469c5b9fe1e250de7d18"])
