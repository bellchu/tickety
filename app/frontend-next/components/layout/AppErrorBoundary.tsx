"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(_error: Error, _info: ErrorInfo) {
    // One malformed message must never unmount the whole app; the boundary
    // below lets the user recover instead of staring at a blank page.
  }

  render() {
    if (this.state.hasError) {
      return (
        <main className="grid min-h-screen place-items-center bg-linen-100 p-6">
          <div className="max-w-md rounded-2xl border border-linen-400 bg-white p-6 text-center shadow-sm">
            <h1 className="text-lg font-semibold text-ink-700">Something went wrong</h1>
            <p className="mt-2 text-sm text-ink-500">
              The app hit an unexpected error. Your data is safe — reload to continue.
            </p>
            <button
              type="button"
              onClick={() => {
                this.setState({ hasError: false });
                window.location.reload();
              }}
              className="mt-4 inline-flex items-center justify-center rounded-md bg-clay-500 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-clay-600 focus:outline-none focus:ring-2 focus:ring-clay-400 focus:ring-offset-2"
            >
              Reload
            </button>
          </div>
        </main>
      );
    }
    return this.props.children;
  }
}
