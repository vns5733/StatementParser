import os, re, sys, glob, argparse
import xlrd, xlwt
from xlutils.copy import copy as xl_copy


def mask_name(value):
    prefix_match = re.match(r'(MR\s{1,5}|MRS\s{1,4}|MS\s{1,5}|DR\s{1,5})', value, re.IGNORECASE)
    prefix = ''
    rest = value
    if prefix_match:
        prefix = prefix_match.group(0)
        rest = value[len(prefix):]
    return prefix + ' '.join('x' * len(w) for w in rest.split())


def mask_account_no(v):
    return re.sub(r'(Account No\s*:\s*)(\S+)', lambda m: m.group(1) + 'x' * len(m.group(2)), v, flags=re.IGNORECASE)


def mask_cust_id(v):
    return re.sub(r'(Cust ID\s*:\s*)(\S+)', lambda m: m.group(1) + '0' * len(m.group(2)), v, flags=re.IGNORECASE)


def mask_micr(v):
    return re.sub(r'(MICR\s*:\s*)(\S+)', lambda m: m.group(1) + 'x' * len(m.group(2)), v, flags=re.IGNORECASE)


def mask_email(v):
    def _r(m):
        return m.group(1) + 'x' * min(len(m.group(2)), 5) + '@' + m.group(3).upper()
    return re.sub(r'(Email\s*:\s*)([^@\s]+)@(\S+)', _r, v, flags=re.IGNORECASE)


def mask_branch(v):
    return re.sub(r'(Account Branch\s*:\s*)(.+)', lambda m: m.group(1) + ' '.join('x' * len(w) for w in m.group(2).split()), v, flags=re.IGNORECASE)


def mask_open_date(v):
    return re.sub(r'(A/C Open Date\s*:\s*)(\S+)', lambda m: m.group(1) + re.sub(r'\d', 'x', m.group(2)), v, flags=re.IGNORECASE)


def mask_cell(row_idx, col_idx, value):
    if value is None:
        return value
    if isinstance(value, float) and value != value:
        return value
    s = str(value).strip()
    if not s:
        return value
    if col_idx == 0:
        if row_idx == 5:
            return mask_name(s)
        if 6 <= row_idx <= 10:
            if s == '.':
                return value
            return ' '.join('x' * len(w) for w in s.split())
    if col_idx == 4:
        if 'Account Branch' in s:
            return mask_branch(s)
        if 'Email' in s:
            return mask_email(s)
        if 'Cust ID' in s:
            return mask_cust_id(s)
        if 'Account No' in s:
            return mask_account_no(s)
        if 'A/C Open Date' in s:
            return mask_open_date(s)
        if 'MICR' in s:
            return mask_micr(s)
    return value


def mask_file(input_path, output_path):
    print('  Reading : ' + input_path)
    wb_r = xlrd.open_workbook(input_path, formatting_info=True)
    wb_w = xl_copy(wb_r)
    for si in range(wb_r.nsheets):
        sr = wb_r.sheet_by_index(si)
        sw = wb_w.get_sheet(si)
        hdr_end = min(19, sr.nrows)
        for ri in range(hdr_end):
            for ci in range(sr.ncols):
                orig = sr.cell(ri, ci).value
                masked = mask_cell(ri, ci, orig)
                if masked != orig:
                    sw.write(ri, ci, masked)
    wb_w.save(output_path)
    print('  Written : ' + output_path)


def mask_dir(in_dir, out_sub='masked'):
    out_dir = os.path.join(in_dir, out_sub)
    os.makedirs(out_dir, exist_ok=True)
    files = sorted(glob.glob(os.path.join(in_dir, '*.xls')))
    if not files:
        print('No .xls files in ' + in_dir)
        return
    print('Found ' + str(len(files)) + ' file(s). Output -> ' + out_dir)
    ok = err = 0
    for fp in files:
        fn = os.path.basename(fp)
        try:
            mask_file(fp, os.path.join(out_dir, fn))
            ok += 1
        except Exception as e:
            print('  ERROR ' + fn + ': ' + str(e))
            err += 1
    print('Done: ' + str(ok) + ' masked, ' + str(err) + ' failed. Output: ' + out_dir)


def main():
    p = argparse.ArgumentParser(description='Mask PII in HDFC Bank statement XLS files.')
    p.add_argument('file', nargs='?', default=None, help='Specific .xls file to mask.')
    p.add_argument('--dir', default=None, help='Folder with .xls files to batch-mask.')
    p.add_argument('--output', default='masked', help='Output subfolder name (default: masked).')
    a = p.parse_args()

    if a.file:
        if not os.path.isfile(a.file):
            print('ERROR: ' + a.file + ' not found')
            sys.exit(1)
        in_dir = os.path.dirname(os.path.abspath(a.file))
        out_dir = os.path.join(in_dir, a.output)
        os.makedirs(out_dir, exist_ok=True)
        mask_file(os.path.abspath(a.file), os.path.join(out_dir, os.path.basename(a.file)))
    else:
        tgt = os.path.abspath(a.dir) if a.dir else os.getcwd()
        if not os.path.isdir(tgt):
            print('ERROR: ' + tgt + ' not found')
            sys.exit(1)
        mask_dir(tgt, a.output)


if __name__ == '__main__':
    main()
