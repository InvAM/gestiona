"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Tooltip } from "radix-ui";
import { useState } from "react";
import { Toaster } from "sonner";
import { ApiError } from "@/lib/api/client";

export function Providers({ children }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            refetchOnWindowFocus: true,
            retry: (count, err) =>
              !(err instanceof ApiError && [401, 403, 404, 422].includes(err.status)) && count < 2,
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <Tooltip.Provider delayDuration={300} skipDelayDuration={100}>
        {children}
      </Tooltip.Provider>
      <Toaster position="bottom-left" richColors closeButton duration={4000} />
    </QueryClientProvider>
  );
}
