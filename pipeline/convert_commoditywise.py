from __future__ import annotations
import argparse, logging, re, sys
from datetime import datetime
from pathlib import Path
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from pipeline.config import DATA_RAW, CONTRACTS

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S')
log = logging.getLogger('pipeline.convert_commoditywise')
GOLD_SYMBOLS = set(CONTRACTS.keys())


def _find_col(df, keyword):
    for c in df.columns:
        if keyword in c.lower():
            return c
    return None


def _try_parse_date(val):
    val = str(val).strip()
    for fmt in ('%d %b %Y', '%d %B %Y'):
        try:
            return datetime.strptime(val, fmt)
        except ValueError:
            pass
    return None


def _is_commoditywise(df):
    date_col = _find_col(df, 'date')
    if date_col is None:
        return False
    valid = [_try_parse_date(v) for v in df[date_col].astype(str)]
    valid = [d for d in valid if d is not None]
    return len(set(valid)) > 1


def _existing_datewise_dates(output_dir):
    existing = set()
    for p in output_dir.glob('BhavCopyDateWise_*.csv'):
        m = re.search(r'BhavCopyDateWise_(\d{8})\.csv', p.name)
        if m:
            existing.add(m.group(1))
    return existing


def collect_all_commoditywise(input_dir):
    '''Collect all commodity-wise CSVs into one combined DataFrame.'''
    csv_files = sorted(input_dir.glob('*.csv'))
    frames = []
    n_detected = 0
    for csv_path in csv_files:
        try:
            df = pd.read_csv(csv_path, dtype=str)
        except Exception as exc:
            log.warning('  %s: read error - %s', csv_path.name, exc)
            continue
        if not _is_commoditywise(df):
            continue
        n_detected += 1
        date_col = _find_col(df, 'date')
        sym_col = _find_col(df, 'symbol')
        inst_col = _find_col(df, 'instrument')
        if date_col is None or sym_col is None:
            log.warning('  %s: missing Date/Symbol column', csv_path.name)
            continue
        if inst_col is not None:
            df = df[df[inst_col].astype(str).str.strip().str.upper() == 'FUTCOM'].copy()
        df = df[df[sym_col].astype(str).str.strip().str.upper().isin(GOLD_SYMBOLS)].copy()
        if df.empty:
            continue
        df['_parsed_date'] = [_try_parse_date(str(v)) for v in df[date_col].astype(str)]
        df = df[df['_parsed_date'].notna()].copy()
        frames.append(df)
    log.info('Detected %d commodity-wise file(s).', n_detected)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    log.info('Collected %d rows across %d unique dates.',
             len(combined), combined['_parsed_date'].nunique())
    return combined


def write_datewise_files(combined, output_dir, existing_dates, dry_run):
    '''Group combined by date; write merged BhavCopyDateWise_DDMMYYYY.csv files.'''
    new_files, skipped, new_dates = 0, 0, []
    for dt, group in combined.groupby('_parsed_date'):
        ddmmyyyy = dt.strftime('%d%m%Y')
        out_fname = 'BhavCopyDateWise_%s.csv' % ddmmyyyy
        out_path = output_dir / out_fname
        if ddmmyyyy in existing_dates:
            skipped += 1
            continue
        out_df = group.drop(columns=['_parsed_date']).reset_index(drop=True)
        sym_col = _find_col(out_df, 'symbol')
        syms = out_df[sym_col].str.strip().unique().tolist() if sym_col else '?'
        if dry_run:
            log.info('  [DRY RUN] %s  %d rows  %s', out_fname, len(out_df), syms)
        else:
            out_df.to_csv(out_path, index=False)
            log.info('  Wrote %s  %d rows  symbols=%s', out_fname, len(out_df), syms)
        new_files += 1
        new_dates.append(dt)
        existing_dates.add(ddmmyyyy)
    return new_files, skipped, new_dates


def verify_sample(output_dir, n=3):
    files_2024 = sorted(output_dir.glob('BhavCopyDateWise_*2024.csv'))[:n]
    log.info('Verification: %d sample files', len(files_2024))
    for p in files_2024:
        try:
            df = pd.read_csv(p)
            date_col = _find_col(df, 'date')
            sym_col = _find_col(df, 'symbol')
            syms = df[sym_col].str.strip().unique().tolist() if sym_col else '?'
            dates = df[date_col].unique().tolist()[:1] if date_col else '?'
            log.info('  %s: %d rows  symbols=%s  date=%s', p.name, len(df), syms, dates)
        except Exception as exc:
            log.warning('  %s: error - %s', p.name, exc)


def main():
    parser = argparse.ArgumentParser(
        description='Convert commodity-wise MCX CSVs to per-date DateWise format.')
    parser.add_argument('--input-dir', type=Path, default=DATA_RAW)
    parser.add_argument('--output-dir', type=Path, default=DATA_RAW)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    log.info('=' * 60)
    log.info('AuraSpread - Commodity-wise -> DateWise CSV Converter')
    log.info('Input  : %s', args.input_dir)
    log.info('Output : %s', output_dir)
    log.info('Dry run: %s', args.dry_run)
    log.info('=' * 60)
    combined = collect_all_commoditywise(args.input_dir)
    if combined.empty:
        log.info('No commodity-wise files found or no GOLD FUTCOM rows.')
        return
    existing_dates = _existing_datewise_dates(output_dir)
    log.info('Existing DateWise files: %d', len(existing_dates))
    new_files, skipped, new_dates = write_datewise_files(
        combined=combined, output_dir=output_dir,
        existing_dates=existing_dates, dry_run=args.dry_run)
    date_min = min(new_dates).date() if new_dates else None
    date_max = max(new_dates).date() if new_dates else None
    log.info('')
    log.info('=' * 60)
    log.info('Conversion complete!')
    log.info('  New files created : %d', new_files)
    log.info('  Dates skipped     : %d (already existed)', skipped)
    log.info('  Date range        : %s -> %s', date_min, date_max)
    log.info('=' * 60)
    if not args.dry_run and new_files > 0:
        verify_sample(output_dir)


if __name__ == '__main__':
    main()
