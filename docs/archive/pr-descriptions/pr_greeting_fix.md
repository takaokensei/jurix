# fix: Prevent Duplicate Greeting Text in Streaming

## 🐛 Bug Fixed

**Problem:** Greeting was showing "Olá, Olá, AdAmdimnin" instead of "Olá, Admin" due to multiple simultaneous streaming executions and reading already-streamed text.

## ✅ Solution

- Added `isStreamingGreeting` guard flag to prevent multiple simultaneous executions
- Get name from `data-user-name` attribute BEFORE clearing elements
- Clear elements immediately to prevent reading already-streamed text
- Reset flag after streaming completes

## 🛠️ Technical Changes

- Added flag check at the start of `showWelcomeStateWithStreaming()`
- Changed order: read attribute → clear elements → stream
- Reset flag when streaming completes

