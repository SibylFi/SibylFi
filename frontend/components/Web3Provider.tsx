'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';
import { WagmiProvider } from 'wagmi';

import { wagmiConfig } from '@/lib/wagmi';

/**
 * Web3 provider used by pages that need wallet connect / ENS resolution
 * (currently /forge). Kept page-scoped so the home leaderboard doesn't pay
 * the bundle cost when no wallet interaction is needed.
 */
export function Web3Provider({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => new QueryClient());
  return (
    <WagmiProvider config={wagmiConfig}>
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    </WagmiProvider>
  );
}
