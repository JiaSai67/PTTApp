from PIL import Image

img = Image.open(r"G:\python\anjian\PTTApp\icon\mic_off_raw.png").convert("RGBA")
datas = img.getdata()

new_data = []
for item in datas:
    # Remove white background (if R, G, B are all > 200, make it transparent)
    if item[0] > 200 and item[1] > 200 and item[2] > 200:
        new_data.append((255, 255, 255, 0))
    else:
        # It's part of the icon. Let's ensure it's a solid red for visibility, or just keep its original color.
        # The user said "我只要紅色的麥克風...", maybe the original is already red. Let's keep original for now.
        new_data.append(item)

img.putdata(new_data)
img.save(r"G:\python\anjian\PTTApp\icon\mic_off.png", "PNG")
print("Image background removed.")
