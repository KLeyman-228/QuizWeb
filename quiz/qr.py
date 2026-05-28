FORMAT_DIVISOR = 0x537
FORMAT_MASK = 0x5412
GF_POLY = 0x11D

VERSION = 5
SIZE = 21 + (VERSION - 1) * 4
DATA_CODEWORDS = 108
ECC_CODEWORDS = 26
MAX_BYTE_LENGTH = DATA_CODEWORDS - 3
QUIET_ZONE = 4


def make_qr_svg(text):
    matrix = make_qr_matrix(text)
    view_size = SIZE + QUIET_ZONE * 2
    commands = []

    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                commands.append(f"M{x + QUIET_ZONE},{y + QUIET_ZONE}h1v1h-1z")

    path_data = "".join(commands)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view_size} {view_size}" '
        f'width="{view_size}" height="{view_size}" shape-rendering="crispEdges">'
        '<rect width="100%" height="100%" fill="#fff"/>'
        f'<path fill="#000" d="{path_data}"/>'
        "</svg>"
    )


def make_qr_matrix(text):
    data = text.encode("utf-8")
    if len(data) > MAX_BYTE_LENGTH:
        raise ValueError("QR payload is too long")

    codewords = make_codewords(data)
    bits = []
    for codeword in codewords:
        bits.extend(((codeword >> shift) & 1) == 1 for shift in range(7, -1, -1))

    base_matrix, function_modules = make_function_pattern()
    best_matrix = None
    best_penalty = None

    for mask in range(8):
        matrix = [row[:] for row in base_matrix]
        place_data_bits(matrix, function_modules, bits, mask)
        draw_format_bits(matrix, mask)
        penalty = calculate_penalty(matrix)

        if best_penalty is None or penalty < best_penalty:
            best_penalty = penalty
            best_matrix = matrix

    return best_matrix


def make_codewords(data):
    bit_buffer = []
    append_bits(bit_buffer, 0b0100, 4)
    append_bits(bit_buffer, len(data), 8)
    for byte in data:
        append_bits(bit_buffer, byte, 8)

    capacity_bits = DATA_CODEWORDS * 8
    terminator = min(4, capacity_bits - len(bit_buffer))
    bit_buffer.extend([False] * terminator)
    while len(bit_buffer) % 8:
        bit_buffer.append(False)

    pad_bytes = [0xEC, 0x11]
    pad_index = 0
    while len(bit_buffer) < capacity_bits:
        append_bits(bit_buffer, pad_bytes[pad_index % 2], 8)
        pad_index += 1

    data_codewords = [
        bits_to_int(bit_buffer[index:index + 8])
        for index in range(0, len(bit_buffer), 8)
    ]
    return data_codewords + reed_solomon_remainder(data_codewords, ECC_CODEWORDS)


def append_bits(buffer, value, length):
    for shift in range(length - 1, -1, -1):
        buffer.append(((value >> shift) & 1) == 1)


def bits_to_int(bits):
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def make_function_pattern():
    matrix = [[False for _ in range(SIZE)] for _ in range(SIZE)]
    function_modules = [[False for _ in range(SIZE)] for _ in range(SIZE)]

    draw_finder_pattern(matrix, function_modules, 0, 0)
    draw_finder_pattern(matrix, function_modules, SIZE - 7, 0)
    draw_finder_pattern(matrix, function_modules, 0, SIZE - 7)
    draw_alignment_pattern(matrix, function_modules, 30, 30)
    draw_timing_patterns(matrix, function_modules)

    set_function_module(matrix, function_modules, 8, 4 * VERSION + 9, True)
    reserve_format_modules(function_modules)

    return matrix, function_modules


def set_function_module(matrix, function_modules, x, y, dark):
    if 0 <= x < SIZE and 0 <= y < SIZE:
        matrix[y][x] = dark
        function_modules[y][x] = True


def draw_finder_pattern(matrix, function_modules, x, y):
    for dy in range(-1, 8):
        for dx in range(-1, 8):
            xx = x + dx
            yy = y + dy
            if not (0 <= xx < SIZE and 0 <= yy < SIZE):
                continue

            dark = (
                0 <= dx <= 6
                and 0 <= dy <= 6
                and (dx in {0, 6} or dy in {0, 6} or (2 <= dx <= 4 and 2 <= dy <= 4))
            )
            set_function_module(matrix, function_modules, xx, yy, dark)


def draw_alignment_pattern(matrix, function_modules, x, y):
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            distance = max(abs(dx), abs(dy))
            set_function_module(matrix, function_modules, x + dx, y + dy, distance != 1)


def draw_timing_patterns(matrix, function_modules):
    for index in range(8, SIZE - 8):
        dark = index % 2 == 0
        set_function_module(matrix, function_modules, index, 6, dark)
        set_function_module(matrix, function_modules, 6, index, dark)


def reserve_format_modules(function_modules):
    for index in range(9):
        if index != 6:
            function_modules[8][index] = True
            function_modules[index][8] = True

    for index in range(8):
        function_modules[8][SIZE - 1 - index] = True
        function_modules[SIZE - 1 - index][8] = True


def place_data_bits(matrix, function_modules, bits, mask):
    bit_index = 0
    upward = True
    x = SIZE - 1

    while x > 0:
        if x == 6:
            x -= 1

        for vertical_index in range(SIZE):
            y = SIZE - 1 - vertical_index if upward else vertical_index
            for dx in range(2):
                xx = x - dx
                if function_modules[y][xx]:
                    continue

                bit = bits[bit_index] if bit_index < len(bits) else False
                if mask_applies(mask, xx, y):
                    bit = not bit
                matrix[y][xx] = bit
                bit_index += 1

        upward = not upward
        x -= 2


def mask_applies(mask, x, y):
    if mask == 0:
        return (x + y) % 2 == 0
    if mask == 1:
        return y % 2 == 0
    if mask == 2:
        return x % 3 == 0
    if mask == 3:
        return (x + y) % 3 == 0
    if mask == 4:
        return (y // 2 + x // 3) % 2 == 0
    if mask == 5:
        return (x * y) % 2 + (x * y) % 3 == 0
    if mask == 6:
        return ((x * y) % 2 + (x * y) % 3) % 2 == 0
    return ((x + y) % 2 + (x * y) % 3) % 2 == 0


def draw_format_bits(matrix, mask):
    error_correction_level = 0b01
    data = (error_correction_level << 3) | mask
    bits = calculate_format_bits(data)

    for index in range(6):
        matrix[index][8] = get_bit(bits, index)
    matrix[7][8] = get_bit(bits, 6)
    matrix[8][8] = get_bit(bits, 7)
    matrix[8][7] = get_bit(bits, 8)
    for index in range(9, 15):
        matrix[8][14 - index] = get_bit(bits, index)

    for index in range(8):
        matrix[8][SIZE - 1 - index] = get_bit(bits, index)
    for index in range(8, 15):
        matrix[SIZE - 15 + index][8] = get_bit(bits, index)
    matrix[SIZE - 8][8] = True


def calculate_format_bits(data):
    value = data << 10
    for shift in range(14, 9, -1):
        if get_bit(value, shift):
            value ^= FORMAT_DIVISOR << (shift - 10)
    return ((data << 10) | value) ^ FORMAT_MASK


def get_bit(value, index):
    return ((value >> index) & 1) == 1


def reed_solomon_remainder(data, degree):
    generator = reed_solomon_generator(degree)
    result = data + [0] * degree

    for index in range(len(data)):
        factor = result[index]
        if factor == 0:
            continue
        for gen_index, coefficient in enumerate(generator):
            result[index + gen_index] ^= gf_multiply(coefficient, factor)

    return result[-degree:]


def reed_solomon_generator(degree):
    generator = [1]
    for index in range(degree):
        generator = polynomial_multiply(generator, [1, gf_power(2, index)])
    return generator


def polynomial_multiply(left, right):
    result = [0] * (len(left) + len(right) - 1)
    for left_index, left_coefficient in enumerate(left):
        for right_index, right_coefficient in enumerate(right):
            result[left_index + right_index] ^= gf_multiply(left_coefficient, right_coefficient)
    return result


def gf_power(value, exponent):
    result = 1
    for _ in range(exponent):
        result = gf_multiply(result, value)
    return result


def gf_multiply(left, right):
    result = 0
    while right:
        if right & 1:
            result ^= left
        left <<= 1
        if left & 0x100:
            left ^= GF_POLY
        right >>= 1
    return result & 0xFF


def calculate_penalty(matrix):
    return (
        run_penalty(matrix)
        + block_penalty(matrix)
        + finder_like_penalty(matrix)
        + balance_penalty(matrix)
    )


def run_penalty(matrix):
    penalty = 0
    lines = matrix + list(zip(*matrix))

    for line in lines:
        run_color = line[0]
        run_length = 1
        for module in line[1:]:
            if module == run_color:
                run_length += 1
            else:
                if run_length >= 5:
                    penalty += run_length - 2
                run_color = module
                run_length = 1

        if run_length >= 5:
            penalty += run_length - 2

    return penalty


def block_penalty(matrix):
    penalty = 0
    for y in range(SIZE - 1):
        for x in range(SIZE - 1):
            color = matrix[y][x]
            if matrix[y][x + 1] == color and matrix[y + 1][x] == color and matrix[y + 1][x + 1] == color:
                penalty += 3
    return penalty


def finder_like_penalty(matrix):
    penalty = 0
    patterns = (
        (True, False, True, True, True, False, True, False, False, False, False),
        (False, False, False, False, True, False, True, True, True, False, True),
    )
    lines = matrix + [list(column) for column in zip(*matrix)]

    for line in lines:
        for index in range(len(line) - 10):
            window = tuple(line[index:index + 11])
            if window in patterns:
                penalty += 40
    return penalty


def balance_penalty(matrix):
    dark = sum(module for row in matrix for module in row)
    total = SIZE * SIZE
    return abs(dark * 20 - total * 10) // total * 10
