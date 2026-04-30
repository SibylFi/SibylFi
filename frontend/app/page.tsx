'use client';

import dynamic from 'next/dynamic';

const SibylFiPrototype = dynamic(() => import('@/components/SibylFiPrototype'), { ssr: false });

export default function Page() {
  return <SibylFiPrototype />;
}
