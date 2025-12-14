# Bank Statement Parser - Improved Version

## 🎯 Key Improvements

### 1. **Standalone Bank Parsers**
Each bank parser is now completely independent:
- **Maybank** (`maybank.py`) - Handles both MTASB and MBB formats
- **Public Bank** (`public_bank.py`) - Handles PBB format
- **RHB Bank** (`rhb.py`) - Handles RHB format
- **CIMB Bank** (`cimb.py`) - Handles CIMB format
- **Bank Islam** (`bank_islam.py`) - Handles Bank Islam format

**Benefits:**
- Modifying one bank parser will NOT affect other banks
- Each parser has its own logic and configuration
- Easier to debug and maintain
- Can be tested independently

### 2. **Automatic Year Extraction**
- **Removed** the manual "Default Year" input field
- Each parser now automatically extracts the year from the PDF statement
- Looks for year in:
  - Statement headers ("Statement Date", "Period", etc.)
  - Date patterns throughout the document
  - Falls back to current year only if not found

**Benefits:**
- No manual input required
- More accurate date parsing
- Handles multi-year statements correctly

### 3. **Unified Parser Interface**
All parsers now follow the same function signature:
```python
parse_transactions_[bank](pdf, source_filename="")
```

**Parameters:**
- `pdf` - pdfplumber PDF object
- `source_filename` - Name of the file being processed

**Returns:**
- List of transaction dictionaries with standardized fields

### 4. **Consistent Output Format**
Every transaction includes:
```python
{
    "date": "YYYY-MM-DD",      # ISO format
    "description": "...",       # Transaction description
    "debit": 0.0,              # Debit amount
    "credit": 0.0,             # Credit amount
    "balance": 0.0,            # Account balance
    "page": 1,                 # Page number
    "source_file": "...",      # Source filename
    "bank": "Bank Name"        # Bank identifier
}
```

## 📁 File Structure

```
.
├── app.py              # Main Streamlit application
├── maybank.py          # Maybank parser (standalone)
├── public_bank.py      # Public Bank parser (standalone)
├── rhb.py             # RHB Bank parser (standalone)
├── cimb.py            # CIMB Bank parser (standalone)
├── bank_islam.py      # Bank Islam parser (standalone)
└── README.md          # This file
```

## 🚀 Usage

### Installation
```bash
pip install streamlit pdfplumber pandas xlsxwriter
```

### Running the Application
```bash
streamlit run app.py
```

### Processing Statements
1. Select your bank from the dropdown
2. Upload one or more PDF statements
3. Click "Start Processing"
4. View transactions and monthly summary
5. Download results in JSON or XLSX format

## 🔧 How Each Parser Works

### Maybank Parser
- Extracts year from statement header
- Handles two formats:
  - **MTASB**: `DD/MM DESCRIPTION AMOUNT +/- BALANCE`
  - **MBB**: `DD Mon YYYY DESCRIPTION AMOUNT +/- BALANCE`
- Reconstructs broken multi-line descriptions
- Outputs ISO date format (YYYY-MM-DD)

### Public Bank Parser
- Extracts year from statement period
- Matches date lines: `DD/MM DESCRIPTION`
- Handles continuation lines for long descriptions
- Determines debit/credit by comparing balances
- Handles Balance B/F entries

### RHB Bank Parser
- Extracts year from statement header
- Matches transaction lines: `DD Mon DESCRIPTION`
- Looks ahead for continuation lines
- Parses multiple number formats (serial, amounts, balance)
- Determines debit/credit based on keywords

### CIMB Bank Parser
- Extracts year from statement date
- Uses table extraction (grid-based)
- Column mapping: Date, Desc, Ref, Withdrawal, Deposit, Balance
- Handles opening balance entries
- Skips header rows automatically

### Bank Islam Parser
- Extracts year from statement period
- Uses table extraction
- Handles 10-column format
- Normalizes dates to ISO format
- Cleans amounts and descriptions

## 🛠️ Customization

### Adding a New Bank
1. Create a new file: `new_bank.py`
2. Implement year extraction:
   ```python
   def extract_year_from_text(text):
       # Your logic here
       return year_string
   ```
3. Implement main parser:
   ```python
   def parse_transactions_newbank(pdf, source_filename=""):
       # Your parsing logic
       return list_of_transactions
   ```
4. Import in `app.py`:
   ```python
   from new_bank import parse_transactions_newbank
   ```
5. Add to bank selection dropdown and processing logic

### Modifying a Parser
Each parser is independent, so you can:
- Add new patterns
- Adjust date formats
- Change keyword detection
- Modify balance calculations

**WITHOUT affecting other banks!**

## 📊 Features

### Transaction Extraction
- ✅ Date, description, debit, credit, balance
- ✅ Page number and source file tracking
- ✅ Bank identifier for multi-bank processing

### Monthly Summary
- ✅ Grouped by year-month
- ✅ Total debits and credits
- ✅ Net change calculation
- ✅ Ending, lowest, and highest balance
- ✅ Transaction count per month
- ✅ Source file tracking

### Export Options
- ✅ JSON (transactions only)
- ✅ JSON (full report with summary)
- ✅ Excel (multi-sheet with summary)

## 🐛 Troubleshooting

### No Transactions Found
- Check if the correct bank is selected
- Verify PDF is not scanned image (must be text-based)
- Check if statement format matches parser expectations

### Wrong Dates
- Parser automatically extracts year from statement
- Check if statement has clear date headers
- Verify date format matches parser patterns

### Missing Transactions
- Check if table structure is recognized
- Verify amounts are in correct columns
- Look for parsing errors in Streamlit logs

## 📝 Notes

- All parsers handle year extraction automatically
- Date output is always in ISO format (YYYY-MM-DD)
- Each parser is completely independent
- No shared state or configuration between parsers
- Safe to modify individual parsers without affecting others

## 🙏 Credits

Improved version with:
- Standalone bank parsers
- Automatic year extraction
- No cross-bank dependencies
- Better error handling
- Consistent output format
