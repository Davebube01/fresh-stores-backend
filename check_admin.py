import asyncio
from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.core.security import verify_password
from sqlalchemy.future import select

async def check_admin():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == "admin@meatstore.com"))
        user = result.scalars().first()
        if not user:
            print("ADMIN USER NOT FOUND")
            return
        
        print(f"Found user: {user.email}")
        print(f"Is Superuser: {user.is_superuser}")
        print(f"Is Active: {user.is_active}")
        
        is_pass_correct = verify_password("adminpassword123", user.hashed_password)
        print(f"Password 'adminpassword123' is correct: {is_pass_correct}")

if __name__ == "__main__":
    asyncio.run(check_admin())
