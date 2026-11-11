import sys, os
from PIL import Image

old_img = Image.open('scratch/bill_old_700.png')
new_img = Image.open('scratch/option_a_extrabold_overdraw.png')

# Header crop (Y: 50 to 250, X: 50 to 1700)
old_img.crop((50, 50, 1700, 250)).save('scratch/crop_old_header.png')
new_img.crop((50, 50, 1700, 250)).save('scratch/crop_new_header.png')

# Item crop (Y: 350 to 550, X: 50 to 1700)
old_img.crop((50, 350, 1700, 550)).save('scratch/crop_old_items.png')
new_img.crop((50, 350, 1700, 550)).save('scratch/crop_new_items.png')

# Footer crop (Y: 850 to 1200, X: 50 to 1700)
old_img.crop((50, 850, 1700, 1200)).save('scratch/crop_old_footer.png')
new_img.crop((50, 850, 1700, 1200)).save('scratch/crop_new_footer.png')

print('Crops saved successfully.')

