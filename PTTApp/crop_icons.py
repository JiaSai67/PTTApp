from PIL import Image
import os

base_path = r"G:\python\anjian\PTTApp\icon"
img = Image.open(os.path.join(base_path, "new_icon_raw.jpg")).convert("RGBA")

width, height = img.size

# Split image in half, but leave a gap in the middle to avoid overlapping pixels
img_left = img.crop((0, 0, width//2 - 20, height))
img_right = img.crop((width//2 + 10, 0, width, height))

def remove_background(img_obj, is_left):
    datas = img_obj.getdata()
    new_data = []
    # Any white-ish color becomes transparent
    for item in datas:
        # white background -> transparent
        if item[0] > 220 and item[1] > 220 and item[2] > 220:
            new_data.append((255, 255, 255, 0))
        else:
            if is_left:
                # Left image should only contain green, no red
                if item[0] > item[1] + 20: # If it's noticeably red
                    new_data.append((255, 255, 255, 0))
                else:
                    new_data.append(item)
            else:
                new_data.append(item)
                
    img_obj.putdata(new_data)
    # Further crop to bounding box to center it nicely
    bbox = img_obj.getbbox()
    if bbox:
        img_obj = img_obj.crop(bbox)
    return img_obj

mic_on = remove_background(img_left, is_left=True)
mic_off = remove_background(img_right, is_left=False)

mic_on.save(os.path.join(base_path, "mic_on.png"), "PNG")
mic_off.save(os.path.join(base_path, "mic_off.png"), "PNG")
print("Icons processed successfully with fine-tuning.")
