from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from datetime import datetime
import os
import openpyxl
from database import get_db
from models import User, Customer, PurposeSource, FileUpload, UserRole
from auth import get_current_user
from config import UPLOAD_DIR, MAX_FILE_SIZE, ALLOWED_EXTENSIONS
import pandas as pd

router = APIRouter(prefix="/api/upload", tags=["upload"])

def check_pql(current_user: User = Depends(get_current_user)):
    """Check if current user is PQL"""
    if current_user.role != UserRole.PQL.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only PQL can access this endpoint"
        )
    return current_user

# Create upload directory if doesn't exist
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("/cif-name")
async def upload_cif_name(
    file: UploadFile = File(...),
    pql_user: User = Depends(check_pql),
    db: Session = Depends(get_db)
):
    """Upload CIF - Customer Name mapping file"""
    # Validate file
    if file.filename.split('.')[-1].lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File type not allowed. Use .xlsx, .xls, or .csv"
        )
    
    # Check file size
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File size exceeds maximum allowed size"
        )
    
    try:
        # Save file
        file_path = os.path.join(UPLOAD_DIR, f"cif_{pql_user.id}_{datetime.utcnow().timestamp()}.xlsx")
        with open(file_path, "wb") as f:
            f.write(content)
        
        # Parse file
        df = pd.read_excel(file_path)
        records_imported = 0
        errors = []
        
        # Expected columns: CIF, Customer Name
        if 'CIF' not in df.columns or 'Customer Name' not in df.columns:
            # Try common Vietnamese names
            cols = list(df.columns)
            if len(cols) < 2:
                raise ValueError("File must have at least CIF and Customer Name columns")
            cif_col = cols[0]
            name_col = cols[1]
        else:
            cif_col = 'CIF'
            name_col = 'Customer Name'
        
        # Import records
        for idx, row in df.iterrows():
            try:
                cif = str(row[cif_col]).strip()
                customer_name = str(row[name_col]).strip()
                
                if not cif or len(cif) > 10:
                    errors.append(f"Row {idx}: Invalid CIF")
                    continue
                
                # Check if customer exists
                existing = db.query(Customer).filter(Customer.cif == cif).first()
                if existing:
                    existing.customer_name = customer_name
                else:
                    customer = Customer(
                        cif=cif,
                        customer_name=customer_name,
                        pnv_user_id=None  # Will be set later
                    )
                    db.add(customer)
                
                records_imported += 1
            except Exception as e:
                errors.append(f"Row {idx}: {str(e)}")
        
        db.commit()
        
        # Log file upload
        file_log = FileUpload(
            uploaded_by=pql_user.id,
            file_name=file.filename,
            file_path=file_path,
            file_type="cif-name",
            records_imported=records_imported,
            errors="\n".join(errors) if errors else None,
            status="success" if len(errors) == 0 else "partial"
        )
        db.add(file_log)
        db.commit()
        
        return {
            "message": "File uploaded successfully",
            "file_name": file.filename,
            "records_imported": records_imported,
            "errors": errors if errors else None
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error processing file: {str(e)}"
        )

@router.post("/purpose-source")
async def upload_purpose_source(
    file: UploadFile = File(...),
    pql_user: User = Depends(check_pql),
    db: Session = Depends(get_db)
):
    """Upload Purpose/Source file with code and descriptions"""
    # Validate file
    if file.filename.split('.')[-1].lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File type not allowed"
        )
    
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File size exceeds maximum allowed size"
        )
    
    try:
        file_path = os.path.join(UPLOAD_DIR, f"purpose_source_{pql_user.id}_{datetime.utcnow().timestamp()}.xlsx")
        with open(file_path, "wb") as f:
            f.write(content)
        
        # Read file with multiple sheets
        excel_file = pd.ExcelFile(file_path)
        records_imported = 0
        errors = []
        sheets_processed = 0
        
        # Expected sheets: Purpose and Source
        for sheet_name in excel_file.sheet_names:
            try:
                df = pd.read_excel(file_path, sheet_name=sheet_name)
                sheets_processed += 1
                
                # Determine if Purpose or Source based on sheet name
                sheet_type = "purpose" if "purpose" in sheet_name.lower() else "source"
                
                # Expected columns: Code, Description
                code_col = None
                name_col = None
                for col in df.columns:
                    if "code" in str(col).lower():
                        code_col = col
                    if "name" in str(col).lower() or "description" in str(col).lower():
                        name_col = col
                
                if not code_col or not name_col:
                    cols = list(df.columns)
                    code_col = cols[0]
                    name_col = cols[1]
                
                # Import records
                for idx, row in df.iterrows():
                    try:
                        code = int(row[code_col])
                        name = str(row[name_col]).strip()
                        
                        if code < 1 or code > 12:
                            errors.append(f"{sheet_name} Row {idx}: Code must be 1-12")
                            continue
                        
                        # Check if exists
                        existing = db.query(PurposeSource).filter(
                            PurposeSource.code == code,
                            PurposeSource.type == sheet_type
                        ).first()
                        
                        if existing:
                            existing.name = name
                        else:
                            purpose_source = PurposeSource(
                                code=code,
                                name=name,
                                type=sheet_type
                            )
                            db.add(purpose_source)
                        
                        records_imported += 1
                    except Exception as e:
                        errors.append(f"{sheet_name} Row {idx}: {str(e)}")
            
            except Exception as e:
                errors.append(f"Sheet {sheet_name}: {str(e)}")
        
        db.commit()
        
        # Log file upload
        file_log = FileUpload(
            uploaded_by=pql_user.id,
            file_name=file.filename,
            file_path=file_path,
            file_type="purpose-source",
            sheets_processed=sheets_processed,
            records_imported=records_imported,
            errors="\n".join(errors) if errors else None,
            status="success" if len(errors) == 0 else "partial"
        )
        db.add(file_log)
        db.commit()
        
        return {
            "message": "File uploaded successfully",
            "file_name": file.filename,
            "sheets_processed": sheets_processed,
            "records_imported": records_imported,
            "errors": errors if errors else None
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error processing file: {str(e)}"
        )

@router.post("/exchange-rate")
async def upload_exchange_rate(
    file: UploadFile = File(...),
    pql_user: User = Depends(check_pql),
    db: Session = Depends(get_db)
):
    """Upload exchange rate file for balancing"""
    if file.filename.split('.')[-1].lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File type not allowed"
        )
    
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File size exceeds maximum allowed size"
        )
    
    try:
        file_path = os.path.join(UPLOAD_DIR, f"exchange_rate_{pql_user.id}_{datetime.utcnow().timestamp()}.xlsx")
        with open(file_path, "wb") as f:
            f.write(content)
        
        # Log file upload
        file_log = FileUpload(
            uploaded_by=pql_user.id,
            file_name=file.filename,
            file_path=file_path,
            file_type="exchange-rate",
            records_imported=0,
            status="success"
        )
        db.add(file_log)
        db.commit()
        
        return {
            "message": "Exchange rate file uploaded successfully",
            "file_name": file.filename
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error uploading file: {str(e)}"
        )

@router.get("/history")
def get_upload_history(
    pql_user: User = Depends(check_pql),
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 50
):
    """Get file upload history"""
    uploads = db.query(FileUpload).filter(
        FileUpload.uploaded_by == pql_user.id
    ).order_by(FileUpload.uploaded_at.desc()).offset(skip).limit(limit).all()
    
    return {
        "total": len(uploads),
        "uploads": [
            {
                "id": u.id,
                "file_name": u.file_name,
                "file_type": u.file_type,
                "records_imported": u.records_imported,
                "status": u.status,
                "uploaded_at": u.uploaded_at,
                "errors": u.errors
            }
            for u in uploads
        ]
    }
