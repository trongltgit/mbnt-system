from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from datetime import datetime
import pandas as pd
import os
from database import get_db
from models import User, Transaction, Customer, PurposeSource, TransactionStatus, UserRole, BGDManagement, ExchangeRateBalance
from schemas import ReportFilter
from auth import get_current_user
from config import UPLOAD_DIR

router = APIRouter(prefix="/api/reports", tags=["reports"])

def check_pql(current_user: User = Depends(get_current_user)):
    """Check if current user is PQL"""
    if current_user.role != UserRole.PQL.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only PQL can generate reports"
        )
    return current_user

@router.post("/generate")
def generate_report(
    filters: ReportFilter,
    pql_user: User = Depends(check_pql),
    db: Session = Depends(get_db),
    output_format: str = Query("excel", regex="^(excel|pdf)$")
):
    """Generate transaction report based on filters"""
    
    # Build query
    query = db.query(
        Transaction.id,
        Transaction.transaction_no,
        Customer.cif,
        Customer.customer_name,
        User.username.label("pnv_user"),
        User.department.label("pnv_department"),
        Transaction.direction,
        Transaction.currency_code,
        Transaction.amount,
        Transaction.buy_currency,
        Transaction.sell_currency,
        Transaction.buy_rate,
        Transaction.sell_rate,
        Transaction.transaction_date,
        Transaction.effective_date,
        Transaction.transaction_type,
        Transaction.purpose_source_code,
        Transaction.corresponding_amount,
        Transaction.profit,
        Transaction.status,
        Transaction.updated_at
    ).join(
        Customer, Transaction.customer_id == Customer.id
    ).join(
        User, Transaction.pnv_id == User.id
    ).filter(
        Transaction.status == TransactionStatus.ACCEPTED.value
    )
    
    # Apply filters
    if filters.transaction_date_from:
        query = query.filter(Transaction.transaction_date >= filters.transaction_date_from)
    if filters.transaction_date_to:
        query = query.filter(Transaction.transaction_date <= filters.transaction_date_to)
    if filters.effective_date_from:
        query = query.filter(Transaction.effective_date >= filters.effective_date_from)
    if filters.effective_date_to:
        query = query.filter(Transaction.effective_date <= filters.effective_date_to)
    if filters.buy_currency:
        query = query.filter(Transaction.buy_currency == filters.buy_currency)
    if filters.sell_currency:
        query = query.filter(Transaction.sell_currency == filters.sell_currency)
    if filters.pnv_department:
        query = query.filter(User.department == filters.pnv_department)
    if filters.transaction_type:
        query = query.filter(Transaction.transaction_type == filters.transaction_type)
    
    # Execute query
    results = query.all()
    
    if not results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No transactions found matching the filters"
        )
    
    # Convert to DataFrame
    data = []
    for row in results:
        data.append({
            "Transaction No": row.transaction_no,
            "CIF": row.cif,
            "Customer Name": row.customer_name,
            "PNV Department": row.pnv_department,
            "Direction": row.direction,
            "Currency": row.currency_code,
            "Amount": row.amount,
            "Buy Currency": row.buy_currency,
            "Sell Currency": row.sell_currency,
            "Buy Rate": row.buy_rate,
            "Sell Rate": row.sell_rate,
            "Transaction Date": row.transaction_date,
            "Effective Date": row.effective_date,
            "Type": row.transaction_type,
            "Purpose/Source Code": row.purpose_source_code,
            "Corresponding Amount": row.corresponding_amount,
            "Profit": row.profit,
            "Updated": row.updated_at
        })
    
    df = pd.DataFrame(data)
    
    # Calculate summary
    summary = {
        "Total Transactions": len(df),
        "Total Volume": df["Amount"].sum(),
        "Total Profit": df["Profit"].sum() if "Profit" in df.columns else 0,
        "By Transaction Type": df.groupby("Type").size().to_dict() if "Type" in df.columns else {},
        "By Currency": df.groupby("Currency").size().to_dict() if "Currency" in df.columns else {}
    }
    
    # Generate file
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    
    if output_format == "excel":
        file_name = f"MBNT_Report_{timestamp}.xlsx"
        file_path = os.path.join(UPLOAD_DIR, file_name)
        
        with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Transactions", index=False)
            
            # Summary sheet
            summary_df = pd.DataFrame([summary])
            summary_df.to_excel(writer, sheet_name="Summary", index=False)
    
    else:  # pdf
        file_name = f"MBNT_Report_{timestamp}.pdf"
        file_path = os.path.join(UPLOAD_DIR, file_name)
        
        try:
            df.to_html(file_path.replace(".pdf", ".html"), index=False)
            # Would need pdfkit with wkhtmltopdf for real PDF generation
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="PDF export coming soon. Use Excel format for now."
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error generating PDF: {str(e)}"
            )
    
    return {
        "message": "Report generated successfully",
        "file_name": file_name,
        "summary": summary,
        "record_count": len(df)
    }

@router.get("/download/{file_name}")
def download_report(
    file_name: str,
    pql_user: User = Depends(check_pql)
):
    """Download generated report file"""
    file_path = os.path.join(UPLOAD_DIR, file_name)
    
    # Security check
    if not os.path.exists(file_path) or not file_path.startswith(UPLOAD_DIR):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report file not found"
        )
    
    return FileResponse(
        path=file_path,
        media_type="application/octet-stream",
        filename=file_name
    )

@router.post("/export-blotter")
def export_blotter(
    output_format: str = Query("excel", regex="^(excel|pdf)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Export blotter to Excel or PDF"""
    
    # Get transactions based on user role
    query = db.query(
        Transaction.id,
        Transaction.transaction_no,
        Customer.cif,
        Customer.customer_name,
        Transaction.direction,
        Transaction.currency_code,
        Transaction.amount,
        Transaction.buy_currency,
        Transaction.sell_currency,
        Transaction.buy_rate,
        Transaction.sell_rate,
        Transaction.transaction_date,
        Transaction.effective_date,
        Transaction.transaction_type,
        Transaction.corresponding_amount,
        Transaction.profit,
        Transaction.updated_at
    ).join(
        Customer, Transaction.customer_id == Customer.id
    ).filter(
        Transaction.status == TransactionStatus.ACCEPTED.value
    )
    
    # Apply role-based filtering
    if current_user.role == UserRole.PNV.value:
        query = query.filter(Transaction.pnv_id == current_user.id)
    elif current_user.role == UserRole.BGD.value:
        managed_pnv_ids = db.query(BGDManagement).filter(
            BGDManagement.bgd_id == current_user.id
        ).all()
        pnv_ids = [m.pnv_user_id for m in managed_pnv_ids]
        query = query.filter(Transaction.pnv_id.in_(pnv_ids))
    
    results = query.all()
    
    if not results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No transactions to export"
        )
    
    # Convert to DataFrame
    data = []
    for row in results:
        data.append({
            "Transaction No": row.transaction_no,
            "CIF": row.cif,
            "Customer Name": row.customer_name,
            "Direction": row.direction,
            "Currency": row.currency_code,
            "Amount": row.amount,
            "Buy Currency": row.buy_currency,
            "Sell Currency": row.sell_currency,
            "Buy Rate": row.buy_rate,
            "Sell Rate": row.sell_rate,
            "Transaction Date": row.transaction_date,
            "Effective Date": row.effective_date,
            "Type": row.transaction_type,
            "Corresponding Amount": row.corresponding_amount,
            "Profit": row.profit,
            "Last Updated": row.updated_at
        })
    
    df = pd.DataFrame(data)
    
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    
    if output_format == "excel":
        file_name = f"Blotter_{timestamp}.xlsx"
        file_path = os.path.join(UPLOAD_DIR, file_name)
        df.to_excel(file_path, index=False)
    else:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="PDF export coming soon"
        )
    
    return {
        "message": "Blotter exported successfully",
        "file_name": file_name,
        "record_count": len(df)
    }

@router.get("/balance-rates/{transaction_id}")
def get_balance_rates(
    transaction_id: int,
    pql_user: User = Depends(check_pql),
    db: Session = Depends(get_db)
):
    """Get exchange rate balance for a transaction"""
    balance = db.query(ExchangeRateBalance).filter(
        ExchangeRateBalance.transaction_id == transaction_id
    ).first()
    
    if not balance:
        return {
            "transaction_id": transaction_id,
            "balance_rate": None,
            "message": "No balance rate set"
        }
    
    return {
        "transaction_id": transaction_id,
        "balance_rate": balance.balance_rate,
        "created_by": balance.created_by,
        "created_at": balance.created_at,
        "updated_at": balance.updated_at
    }
