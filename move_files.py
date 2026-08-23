import os
import shutil

src_dir = r"g:\python\anjian\PTTApp"
dest_dir = r"g:\python\anjian"

for item in os.listdir(src_dir):
    s = os.path.join(src_dir, item)
    d = os.path.join(dest_dir, item)
    if os.path.exists(d):
        if os.path.isdir(d):
            shutil.rmtree(d)
        else:
            os.remove(d)
    shutil.move(s, d)

os.rmdir(src_dir)
print("Moved successfully")
