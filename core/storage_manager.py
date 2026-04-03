"""
Storage Manager - Handles report organization and cleanup
Organizes reports by location and type
Auto-archives old reports
"""

import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from config.settings import BASE_OUTPUT

# =============================================
# STORAGE STRUCTURE
# =============================================

def get_report_path(location, report_type):
    """
    Get or create report path for location/type
    
    Structure:
    storage/reports/
      ├── BellsBeach/
      │   ├── Surf/
      │   ├── Weather/
      │   └── Sky/
      ├── Birregurra/
      │   ├── Weather/
      │   └── Sky/
      └── _archive/
    """
    report_type_clean = report_type.lower()
    
    report_dir = os.path.join(BASE_OUTPUT, location, report_type_clean)
    os.makedirs(report_dir, exist_ok=True)
    
    print(f"[STORAGE] Report path: {report_dir}")
    return report_dir

def get_archive_path(location, report_type):
    """Get archive path for old reports"""
    archive_dir = os.path.join(BASE_OUTPUT, "_archive", location, report_type.lower())
    os.makedirs(archive_dir, exist_ok=True)
    return archive_dir

# =============================================
# SAVE REPORT
# =============================================

def save_report(location, report_type, source_file):
    """
    Save report to organized location
    
    Args:
        location: Location name
        report_type: "Surf", "Weather", "Sky"
        source_file: Path to generated PDF
    
    Returns:
        Destination path
    """
    if not os.path.exists(source_file):
        print(f"[ERROR] Source file not found: {source_file}")
        return None
    
    try:
        dest_dir = get_report_path(location, report_type)
        dest_file = os.path.join(dest_dir, os.path.basename(source_file))
        
        # Copy file to organized location
        shutil.copy2(source_file, dest_file)
        print(f"[OK] Report saved: {dest_file}")
        
        return dest_file
    except Exception as e:
        print(f"[ERROR] Failed to save report: {e}")
        return None

# =============================================
# CLEANUP & ARCHIVE
# =============================================

def cleanup_old_reports(location=None, days_old=90, keep_latest=10):
    """
    Archive reports older than X days
    Keep latest X reports in active folder
    
    Args:
        location: Specific location or None for all
        days_old: Archive reports older than this many days
        keep_latest: Always keep this many latest reports
    """
    
    print(f"\n[CLEANUP] Starting report cleanup (>{days_old} days old)...")
    
    locations = [location] if location else get_all_locations()
    archived_count = 0
    
    for loc in locations:
        report_types = ["Surf", "Weather", "Sky"]
        
        for report_type in report_types:
            report_dir = get_report_path(loc, report_type)
            
            if not os.path.exists(report_dir):
                continue
            
            # Get all PDFs sorted by date (oldest first)
            pdf_files = sorted(
                [f for f in os.listdir(report_dir) if f.endswith('.pdf')],
                key=lambda x: os.path.getmtime(os.path.join(report_dir, x))
            )
            
            cutoff_date = datetime.now() - timedelta(days=days_old)
            
            for pdf in pdf_files[:-keep_latest]:  # Keep latest X
                file_path = os.path.join(report_dir, pdf)
                file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                
                if file_mtime < cutoff_date:
                    try:
                        archive_dir = get_archive_path(loc, report_type)
                        archive_path = os.path.join(archive_dir, pdf)
                        shutil.move(file_path, archive_path)
                        print(f"[OK] Archived: {pdf}")
                        archived_count += 1
                    except Exception as e:
                        print(f"[WARN] Failed to archive {pdf}: {e}")
    
    print(f"[OK] Cleanup complete. Archived {archived_count} report(s)\n")

def get_all_locations():
    """Get list of all location folders"""
    try:
        locations = [
            d for d in os.listdir(BASE_OUTPUT) 
            if os.path.isdir(os.path.join(BASE_OUTPUT, d)) and not d.startswith('_')
        ]
        return sorted(locations)
    except:
        return []

# =============================================
# REPORT BROWSER
# =============================================

def get_recent_reports(location=None, days=7):
    """Get recent reports"""
    reports = []
    cutoff = datetime.now() - timedelta(days=days)
    
    locations = [location] if location else get_all_locations()
    
    for loc in locations:
        for report_type in ["Surf", "Weather", "Sky"]:
            report_dir = get_report_path(loc, report_type)
            
            if not os.path.exists(report_dir):
                continue
            
            for pdf in os.listdir(report_dir):
                if pdf.endswith('.pdf'):
                    file_path = os.path.join(report_dir, pdf)
                    file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                    
                    if file_mtime > cutoff:
                        reports.append({
                            'location': loc,
                            'type': report_type,
                            'filename': pdf,
                            'path': file_path,
                            'date': file_mtime
                        })
    
    return sorted(reports, key=lambda x: x['date'], reverse=True)

def get_latest_report(location, report_type):
    """Get most recent report for location/type"""
    report_dir = get_report_path(location, report_type)
    
    if not os.path.exists(report_dir):
        return None
    
    pdfs = sorted(
        [f for f in os.listdir(report_dir) if f.endswith('.pdf')],
        key=lambda x: os.path.getmtime(os.path.join(report_dir, x)),
        reverse=True
    )
    
    if pdfs:
        return os.path.join(report_dir, pdfs[0])
    return None

# =============================================
# TEST
# =============================================

if __name__ == "__main__":
    print("Storage Manager Test\n")
    
    # Show locations
    print("Locations:", get_all_locations())
    
    # Show recent reports
    print("\nRecent reports (last 7 days):")
    for report in get_recent_reports()[:5]:
        print(f"  - {report['location']}/{report['type']}: {report['filename']}")
    
    # Cleanup
    cleanup_old_reports(days_old=90, keep_latest=10)