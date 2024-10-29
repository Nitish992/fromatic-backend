import io
import os
from dataclasses import fields

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.responses import JSONResponse
import pandas as pd
import json
from nanoid import generate
from io import BytesIO
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.middleware.cors import CORSMiddleware

from app.database import SessionLocal, get_db
from app.models import User, Form, Response
from app.schemas import UserCreate, FormResponse, ResponseData, FormField

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],  # Your Next.js frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/register/")
async def register_user(user_data: UserCreate):
    # Create a new database session
    db: Session = SessionLocal()

    try:
        # Check if the user already exists by `clerk_user_id`
        existing_user = db.query(User).filter(User.clerk_user_id == user_data.clerk_user_id).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="User already registered.")

        # Create a new user object
        new_user = User(clerk_user_id=user_data.clerk_user_id, email=user_data.email)

        # Add to the database and commit
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        return {"message": "User registered successfully", "user_id": new_user.id}

    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="User with this email or Clerk ID already exists.")

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error registering user: {str(e)}")

    finally:
        # Always close the session
        db.close()

# File upload route

@app.post("/upload/")
async def upload_file(file: UploadFile = File(...), user_id: int = None):
    form_name = ""
    fields = []
    print(user_id)
    if not file.filename.endswith(('.json', '.xlsx')):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a JSON or Excel file.")

    # Read the file content
    contents = await file.read()

    if file.filename.endswith('.json'):
        data = json.loads(contents)
        form_name = data.get("formName")
        fields = data.get("fields")

        if not form_name or not fields:
            raise HTTPException(status_code=400, detail="JSON must contain 'formName' and 'fields'.")

    elif file.filename.endswith('.xlsx'):
        #print("is excel file")

        # df = pd.read_excel(io.BytesIO(contents), engine='openpyxl')
        # form_name = file.filename  # Use the filename for form name if Excel
        # fields = df.to_dict(orient='records')
        # print("Fields from excel: ",fields)
        try:
            df = pd.read_excel(io.BytesIO(contents), engine='openpyxl')

            # Clean up and transform the DataFrame
            fields = []
            for _, row in df.iterrows():
                field_json = {
                    "label": row.get("Label", "").strip(),
                    "type": row.get("Type", "").strip(),
                    "validation": {
                        "required": row.get("Required", "").strip().lower() == 'yes'
                    }
                }

                # Add options only if type is Dropdown or Multiple Choice
                if field_json["type"] in ["Dropdown", "Multiple Choice"]:
                    options = row.get("Option", "")
                    field_json["options"] = [option.strip() for option in options.split(",") if option.strip()]

                # Exclude empty fields
                if field_json["type"] in ["Text", "Checkbox"]:
                    field_json.pop("options", None)  # Remove options if type is Text or Checkbox

                fields.append(field_json)



        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error parsing Excel file: {e}")

    # Generate a unique form_id using NanoID
    form_id = generate(size=10)  # 10-character NanoID

    # Save form data to the database
    db = SessionLocal()
    try:
        new_form = Form(form_id=form_id, user_id=user_id, name=form_name, fields=fields)
        db.add(new_form)
        db.commit()
        db.refresh(new_form)

        return JSONResponse(content={"message": "Form uploaded successfully", "form_id": new_form.form_id}, status_code=201)

    except SQLAlchemyError as e:
        db.rollback()
        print(f"Database error: {e}")
        raise HTTPException(status_code=500, detail="Error saving form to the database.")

    finally:
        db.close()


# Route to get form data by form_id
@app.get("/form/{form_id}", response_model=FormResponse)
async def get_form(form_id: str, db: Session = Depends(get_db)):
    try:
        # Retrieve the form using form_id
        form = db.query(Form).filter(Form.form_id == form_id).first()

        if not form:
            raise HTTPException(status_code=404, detail="Form not found")

        # Make sure the fields are in a format that can be serialized
        # Convert JSON string to a Python object if necessary
        fields_data = form.fields
        if isinstance(fields_data, str):
            fields_data = json.loads(fields_data)

        # Create a Pydantic FormResponse object
        form_data = FormResponse(
            form_id=form.form_id,
            name=form.name,
            fields=fields_data  # fields_data should be a list of dictionaries
        )

        return form_data

    except SQLAlchemyError as e:
        print(f"Database error: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving form data.")


@app.post("/form/{formId}/submit")
def submit_form_response(formId: str, response_data: ResponseData, db: Session = Depends(get_db)):
    form = db.query(Form).filter(Form.form_id == formId).first()

    if not form:
        raise HTTPException(status_code=404, detail="Form not found")

    # Save the response in the database
    new_response = Response(
        form_id=form.id,
        data=response_data.data
    )
    db.add(new_response)
    db.commit()
    db.refresh(new_response)

    return {"message": "Response submitted successfully", "response_id": new_response.id}

@app.get("/form/{formId}/responses")
def get_form_responses(formId: str, db: Session = Depends(get_db)):
    form = db.query(Form).filter(Form.form_id == formId).first()

    if not form:
        raise HTTPException(status_code=404, detail="Form not found")

    responses = db.query(Response).filter(Response.form_id == form.id).all()
    return {"form_id": form.form_id, "responses": [response.data for response in responses]}

@app.get("/user/{userId}/forms")
async def get_user_forms(userId: int, db: Session = Depends(get_db)):
    # Query to get forms for the specific user
    forms = db.query(Form).filter(Form.user_id == userId).all()

    if not forms:
        raise HTTPException(status_code=404, detail="No forms found for this user")

    return {
        "userId": userId,
        "forms": [
            {
                "id": form.id,
                "name": form.name,
                "form_id" : form.form_id

            }
            for form in forms
        ]
    }

@app.get("/user/{clerk_user_id}")
async def get_user_id(clerk_user_id: str):
    db: Session = SessionLocal()
    try:
        user = db.query(User).filter(User.clerk_user_id == clerk_user_id).first()
        if user:
            return {"user_id": user.id}
        else:
            raise HTTPException(status_code=404, detail="User not found.")
    finally:
        db.close()
# from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
# from fastapi.responses import JSONResponse
# import pandas as pd
# import json
# from nanoid import generate
# from io import BytesIO
# from sqlalchemy.exc import IntegrityError, SQLAlchemyError
# from sqlalchemy.orm import Session
# from starlette.middleware.cors import CORSMiddleware

# from app.database import SessionLocal, get_db
# from app.models import User, Form, Response
# from app.schemas import UserCreate, FormResponse, ResponseData

# app = FastAPI()

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],  # Your Next.js frontend URL
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )


# @app.post("/register/")
# async def register_user(user_data: UserCreate):
#     # Create a new database session
#     db: Session = SessionLocal()

#     try:
#         # Check if the user already exists by `clerk_user_id`
#         existing_user = db.query(User).filter(User.clerk_user_id == user_data.clerk_user_id).first()
#         if existing_user:
#             raise HTTPException(status_code=400, detail="User already registered.")

#         # Create a new user object
#         new_user = User(clerk_user_id=user_data.clerk_user_id, email=user_data.email)

#         # Add to the database and commit
#         db.add(new_user)
#         db.commit()
#         db.refresh(new_user)

#         return {"message": "User registered successfully", "user_id": new_user.id}

#     except IntegrityError:
#         db.rollback()
#         raise HTTPException(status_code=400, detail="User with this email or Clerk ID already exists.")

#     except Exception as e:
#         db.rollback()
#         raise HTTPException(status_code=500, detail=f"Error registering user: {str(e)}")

#     finally:
#         # Always close the session
#         db.close()

# # File upload route
# @app.post("/upload/")
# async def upload_file(file: UploadFile = File(...), user_id: int = None):
#     print(user_id)
#     if not file.filename.endswith(('.json', '.xlsx')):
#         raise HTTPException(status_code=400, detail="Invalid file type. Please upload a JSON or Excel file.")

#     # Read the file content
#     contents = await file.read()

#     if file.filename.endswith('.json'):
#         data = json.loads(contents)
#         form_name = data.get("formName")
#         fields = data.get("fields")

#         if not form_name or not fields:
#             raise HTTPException(status_code=400, detail="JSON must contain 'formName' and 'fields'.")

#         elif file.filename.endswith('.xlsx'):
#         #print("is excel file")

#         # df = pd.read_excel(io.BytesIO(contents), engine='openpyxl')
#         # form_name = file.filename  # Use the filename for form name if Excel
#         # fields = df.to_dict(orient='records')
#         # print("Fields from excel: ",fields)
#         try:
#             df = pd.read_excel(io.BytesIO(contents), engine='openpyxl')

#             # Clean up and transform the DataFrame
#             fields = []
#             for _, row in df.iterrows():
#                 field_json = {
#                     "label": row.get("Label", "").strip(),
#                     "type": row.get("Type", "").strip(),
#                     "validation": {
#                         "required": row.get("Required", "").strip().lower() == 'yes'
#                     }
#                 }

#                 # Add options only if type is Dropdown or Multiple Choice
#                 if field_json["type"] in ["Dropdown", "Multiple Choice"]:
#                     options = row.get("Option", "")
#                     field_json["options"] = [option.strip() for option in options.split(",") if option.strip()]

#                 # Exclude empty fields
#                 if field_json["type"] in ["Text", "Checkbox"]:
#                     field_json.pop("options", None)  # Remove options if type is Text or Checkbox

#                 fields.append(field_json)



#         except Exception as e:
#             raise HTTPException(status_code=400, detail=f"Error parsing Excel file: {e}")

#     # Generate a unique form_id using NanoID
#     form_id = generate(size=10)  # 10-character NanoID

#     # Save form data to the database
#     db = SessionLocal()
#     try:
#         new_form = Form(form_id=form_id, user_id=user_id, name=form_name, fields=fields)
#         db.add(new_form)
#         db.commit()
#         db.refresh(new_form)

#         return JSONResponse(content={"message": "Form uploaded successfully", "form_id": new_form.form_id}, status_code=201)

#     except SQLAlchemyError as e:
#         db.rollback()
#         print(f"Database error: {e}")
#         raise HTTPException(status_code=500, detail="Error saving form to the database.")

#     finally:
#         db.close()


# # Route to get form data by form_id
# @app.get("/form/{form_id}", response_model=FormResponse)
# async def get_form(form_id: str, db: Session = Depends(get_db)):
#     try:
#         # Retrieve the form using form_id
#         form = db.query(Form).filter(Form.form_id == form_id).first()

#         if not form:
#             raise HTTPException(status_code=404, detail="Form not found")

#         # Make sure the fields are in a format that can be serialized
#         # Convert JSON string to a Python object if necessary
#         fields_data = form.fields
#         if isinstance(fields_data, str):
#             fields_data = json.loads(fields_data)

#         # Create a Pydantic FormResponse object
#         form_data = FormResponse(
#             form_id=form.form_id,
#             name=form.name,
#             fields=fields_data  # fields_data should be a list of dictionaries
#         )

#         return form_data

#     except SQLAlchemyError as e:
#         print(f"Database error: {e}")
#         raise HTTPException(status_code=500, detail="Error retrieving form data.")


# @app.post("/form/{formId}/submit")
# def submit_form_response(formId: str, response_data: ResponseData, db: Session = Depends(get_db)):
#     form = db.query(Form).filter(Form.form_id == formId).first()

#     if not form:
#         raise HTTPException(status_code=404, detail="Form not found")

#     # Save the response in the database
#     new_response = Response(
#         form_id=form.id,
#         data=response_data.data
#     )
#     db.add(new_response)
#     db.commit()
#     db.refresh(new_response)

#     return {"message": "Response submitted successfully", "response_id": new_response.id}

# @app.get("/form/{formId}/responses")
# def get_form_responses(formId: str, db: Session = Depends(get_db)):
#     form = db.query(Form).filter(Form.form_id == formId).first()

#     if not form:
#         raise HTTPException(status_code=404, detail="Form not found")

#     responses = db.query(Response).filter(Response.form_id == form.id).all()
#     return {"form_id": form.form_id, "responses": [response.data for response in responses]}

# @app.get("/user/{userId}/forms")
# async def get_user_forms(userId: int, db: Session = Depends(get_db)):
#     # Query to get forms for the specific user
#     forms = db.query(Form).filter(Form.user_id == userId).all()

#     if not forms:
#         raise HTTPException(status_code=404, detail="No forms found for this user")

#     return {
#         "userId": userId,
#         "forms": [
#             {
#                 "id": form.id,
#                 "name": form.name,
#                 "form_id" : form.form_id

#             }
#             for form in forms
#         ]
#     }

# @app.get("/user/{clerk_user_id}")
# async def get_user_id(clerk_user_id: str):
#     db: Session = SessionLocal()
#     try:
#         user = db.query(User).filter(User.clerk_user_id == clerk_user_id).first()
#         if user:
#             return {"user_id": user.id}
#         else:
#             raise HTTPException(status_code=404, detail="User not found.")
#     finally:
#         db.close()
