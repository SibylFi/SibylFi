import { http, createConfig } from 'wagmi';
import { sepolia, baseSepolia } from 'wagmi/chains';
import { injected } from 'wagmi/connectors';

/**
 * Wagmi config for SibylFi.
 *
 * - Sepolia: where the ENS parent (sibylfi.eth) resolves and where ERC-8004
 *   IdentityRegistry/ReputationRegistry live. ENS lookups run on this chain.
 * - Base Sepolia: where ValidatorSettle and the Durin SibylFiRegistrar live.
 *
 * Only injected connectors (MetaMask, Rabby, Brave, etc.) — no WalletConnect
 * project required for the prototype.
 */
export const wagmiConfig = createConfig({
  chains: [sepolia, baseSepolia],
  connectors: [injected()],
  transports: {
    [sepolia.id]:     http('https://eth-sepolia.public.blastapi.io'),
    [baseSepolia.id]: http('https://base-sepolia-rpc.publicnode.com'),
  },
  ssr: true,
});

declare module 'wagmi' {
  interface Register {
    config: typeof wagmiConfig;
  }
}
