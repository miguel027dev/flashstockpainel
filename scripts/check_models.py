from models import Permission, UserAccessProfile, UserPermission, User, Role

required = [Permission, UserAccessProfile, UserPermission, User, Role]
print("[Flash Stock] Models OK:", ", ".join(model.__name__ for model in required))
