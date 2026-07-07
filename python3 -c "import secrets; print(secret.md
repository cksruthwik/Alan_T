python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # → ALAN_API_TOKEN
FnmrkWVThhjfkSyFWzbn8qVpWeraqyUW4m5rE6_QNBY 
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # → FERNET_KEY
XRBdS6JScalUVuS-0gtjEV1knhbKrVPFvxBbvjIzWZw=

curl -H "Authorization: Bearer Root@SpiderASDFGgdjduidgejsiacaqewsadjgjhteh  " http://localhost:8000/api/v1/health/deps
