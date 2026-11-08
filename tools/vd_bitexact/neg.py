import subprocess, re, sys
muts = {
 "sum_acc_swap": ("msac.l  %d5,%d7,8*(\\i+2)+4(%a4),%d3,%acc3", "msac.l  %d5,%d7,8*(\\i+2)+4(%a4),%d3,%acc1"),
 "pan_no_pol": ("        or.l    %d1,%d4\n        or.l    %d7,%d4", "        or.l    %d7,%d4"),
 "bq_rot": ("        bqf     (\\i+3), %d0, %d2, %d1, %d3, %d4", "        bqf     (\\i+3), %d0, %d1, %d2, %d3, %d4"),
 "p1_rot": ("        p1f     (\\i+1), %d3, %d0, %d2, %d1", "        p1f     (\\i+1), %d3, %d0, %d1, %d2"),
}
src = open("h/new.orig.s").read()
for name, (a, b) in muts.items():
    assert src.count(a) >= 1, name
    open("h/new.s", "w").write(src.replace(a, b, 1))
    subprocess.check_call("cd h && m68k-linux-gnu-as -mcpu=54455 -o new.o new.s && m68k-linux-gnu-ld -o new new.o", shell=True)
    out = subprocess.run(["python3", "drive.py", "6"], capture_output=True, text=True).stdout.strip().split("\n")
    print(name, "->", out[-1])
open("h/new.s", "w").write(src)
subprocess.check_call("cd h && m68k-linux-gnu-as -mcpu=54455 -o new.o new.s && m68k-linux-gnu-ld -o new new.o", shell=True)
