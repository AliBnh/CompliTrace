from pydantic import BaseModel, EmailStr, Field


class UserRegisterRequest(BaseModel):
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    email: EmailStr
    password: str = Field(min_length=1)
    organization_name: str = Field(min_length=1)


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class UserOut(BaseModel):
    id: str
    first_name: str
    last_name: str
    email: EmailStr
    organization_name: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class VerifyResponse(BaseModel):
    valid: bool
    user_id: str
    email: EmailStr
    organization_name: str
