from pathlib import Path


def pre_find_module_path(hook_api):
    python_lib = Path(r"C:\Users\Administrator\AppData\Local\Programs\Python\Python311\Lib")
    hook_api.search_dirs = [str(python_lib)]
