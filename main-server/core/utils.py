
def getModelFields(obj: object) -> str:
    if not hasattr(obj, '_meta'):
        print(f"{obj.__class__.__name__} is not a Django model instance.")
        return

    result: str = f"{obj.__class__.__name__}:\n"

    for field in obj._meta.fields:
        field_name = field.name
        value = getattr(obj, field_name)
        result += f"  {field_name}: {value}\n"

    return result
