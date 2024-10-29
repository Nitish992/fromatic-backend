from typing import Optional, List

from pydantic import BaseModel

# Pydantic model to validate incoming user data
class UserCreate(BaseModel):
    clerk_user_id: str
    email: str


# Define Pydantic model for individual form fields
class FormField(BaseModel):
    label: str
    type: str
    options: Optional[List[str]] = None
    validation: Optional[dict] = None

# Define Pydantic model for the entire form
class FormResponse(BaseModel):
    form_id: str
    name: str
    fields: List[FormField]

class ResponseData(BaseModel):
    data: dict