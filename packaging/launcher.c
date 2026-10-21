/* Native Windows GUI entry point. Uses only the adjacent private runtime. */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0A00
#include <windows.h>
#include <shellapi.h>
#include <wchar.h>
#include <stdlib.h>
#include <stdio.h>

#define PATH_CAP 32768
typedef int (*PythonMain)(int, wchar_t **);

static int fail(const wchar_t *reason, DWORD code) {
    wchar_t message[2048];
    swprintf(message, 2048,
        L"%ls\n\nIšarchyvuokite visą programos ZIP į atskirą aplanką. "
        L"BackUpStudio.exe ir _internal turi likti kartu.\n\n"
        L"Jei buvo sukurtas paleidimo žurnalas, jį rasite:\n"
        L"%%LOCALAPPDATA%%\\BackUpStudio\\startup.log\n\nKodas: %lu", reason, code);
    MessageBoxW(NULL, message, L"BackUp Studio – nepavyko paleisti", MB_OK | MB_ICONERROR);
    return 1;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR command, int show) {
    (void)instance; (void)previous; (void)command; (void)show;
    static wchar_t executable[PATH_CAP], runtime[PATH_CAP], dll[PATH_CAP], script[PATH_CAP];
    DWORD length = GetModuleFileNameW(NULL, executable, PATH_CAP);
    if (!length || length >= PATH_CAP - 128)
        return fail(L"Nepavyko nustatyti programos aplanko.", GetLastError());
    wcscpy(runtime, executable);
    wchar_t *separator = wcsrchr(runtime, L'\\');
    if (!separator) return fail(L"Netinkamas programos kelias.", ERROR_BAD_PATHNAME);
    *separator = L'\0';
    wcscat(runtime, L"\\_internal");
    swprintf(dll, PATH_CAP, L"%ls\\python314.dll", runtime);
    swprintf(script, PATH_CAP, L"%ls\\app\\portable_bootstrap.py", runtime);
    if (GetFileAttributesW(dll) == INVALID_FILE_ATTRIBUTES ||
        GetFileAttributesW(script) == INVALID_FILE_ATTRIBUTES)
        return fail(L"Trūksta programos komponentų.", ERROR_FILE_NOT_FOUND);

    /* Exclude the working directory and PATH from DLL resolution. */
    if (!SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_DEFAULT_DIRS))
        return fail(L"Nepavyko paruošti bibliotekų įkėlimo.", GetLastError());
    DLL_DIRECTORY_COOKIE cookie = AddDllDirectory(runtime);
    if (!cookie) return fail(L"Nepavyko pasiekti programos bibliotekų.", GetLastError());
    HMODULE python = LoadLibraryExW(dll, NULL,
        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    if (!python) return fail(L"Nepavyko įkelti programos vykdymo komponento.", GetLastError());
    union { FARPROC address; PythonMain call; } entry;
    entry.address = GetProcAddress(python, "Py_Main");
    if (!entry.address) return fail(L"Netinkamas programos vykdymo komponentas.", GetLastError());

    int argc = 0;
    wchar_t **original = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (!original) return fail(L"Nepavyko nuskaityti paleidimo parametrų.", GetLastError());
    wchar_t **arguments = calloc((size_t)argc + 4, sizeof(wchar_t *));
    if (!arguments) { LocalFree(original); return fail(L"Nepakanka atminties.", ERROR_NOT_ENOUGH_MEMORY); }
    arguments[0] = executable;
    arguments[1] = L"-I";  /* Isolated: no user Python packages or environment. */
    arguments[2] = L"-B";  /* Never write bytecode into the portable folder. */
    arguments[3] = script;
    for (int i = 1; i < argc; ++i) arguments[i + 3] = original[i];
    int result = entry.call(argc + 3, arguments);
    free(arguments);
    LocalFree(original);
    /* Keep Python/DLLs loaded until process exit; extension finalizers may run. */
    if (result) return fail(L"Programa baigė darbą su klaida.", (DWORD)result);
    return 0;
}
