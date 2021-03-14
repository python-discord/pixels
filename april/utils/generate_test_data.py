import csv
import random

COLUMNS = ['x', 'y', 'rgb', 'user_id', 'deleted']
NUMBER_OF_ROWS = int(1e7)

WIDTH = 160
HEIGHT = 90


with open('postgres/test_data.csv', 'w', newline='') as f:
    file_writer = csv.DictWriter(f, fieldnames=COLUMNS)
    file_writer.writeheader()
    for _ in range(NUMBER_OF_ROWS):
        file_writer.writerow(
            {
                'x': random.randint(0, WIDTH),
                'y': random.randint(0, HEIGHT),
                'rgb': "%06x" % random.randint(0, 0xFFFFFF),
                'user_id': -1,
                'deleted': False
            }
        )
