# Android Client

This module is the Kotlin/Compose client for the ecommerce RAG agent.

## Backend URL

The debug build uses:

```text
http://10.0.2.2:8000
```

That address lets an Android emulator reach the FastAPI server running on the host machine. Start the backend on port `8000` before chatting from the app.

## Build

```powershell
.\gradlew.bat assembleDebug
```

The project uses an app-local debug keystore at `app/debug.keystore` because this workspace cannot write to `C:\Users\Lenovo\.android`.
