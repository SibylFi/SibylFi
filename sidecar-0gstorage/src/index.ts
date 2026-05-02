/**
 * SibylFi 0G Storage sidecar.
 *
 * Wraps @0glabs/0g-ts-sdk and exposes a small HTTP API that the Python
 * agents call as a local dependency on port 7000.
 *
 * In MOCK_MODE, the sidecar stores blobs in an in-memory Map keyed by
 * SHA-256 hash. This lets the full pipeline run offline.
 *
 * Per the zerog-galileo skill, there is no first-party Python SDK for 0G
 * Storage, so this sidecar is the canonical bridge. ~150 lines.
 */
import express, { Request, Response } from 'express';
import { createHash } from 'crypto';

const PORT = 7000;
const MOCK_MODE = process.env.MOCK_MODE !== '0';

const app = express();
app.use(express.json({ limit: '10mb' }));

// ──────────────────────────────────────────────────────────────────────
// In-memory mock store
// ──────────────────────────────────────────────────────────────────────
const mockStore = new Map<string, { content: any; uploadedAt: number }>();

function sha256(payload: string): string {
  return createHash('sha256').update(payload).digest('hex');
}

// ──────────────────────────────────────────────────────────────────────
// 0G client (lazy-initialized — only when MOCK_MODE=0)
// ──────────────────────────────────────────────────────────────────────

let ogClient: any = null;

async function getOGClient() {
  if (ogClient) return ogClient;
  if (MOCK_MODE) {
    throw new Error('not_in_mock_mode');
  }

  // Real-mode initialization. Lazy-import to avoid loading SDK in mock mode.
  // The 0G SDK details may have changed; consult the zerog-galileo skill.
  const { ZgFile, Indexer } = await import('@0glabs/0g-ts-sdk');
  const { ethers } = await import('ethers');

  const provider = new ethers.JsonRpcProvider(
    process.env.OG_GALILEO_RPC || 'https://evmrpc-testnet.0g.ai'
  );
  const signer = new ethers.Wallet(process.env.OG_BROKER_KEY || '0x' + '00'.repeat(32), provider);
  const indexer = new Indexer(
    process.env.OG_INDEXER_URL || 'https://indexer-storage-testnet-turbo.0g.ai'
  );

  ogClient = { ZgFile, indexer, signer };
  return ogClient;
}

// ──────────────────────────────────────────────────────────────────────
// Endpoints
// ──────────────────────────────────────────────────────────────────────

app.get('/', (_req: Request, res: Response) => {
  res.json({
    service: 'sibylfi-sidecar-0gstorage',
    mock_mode: MOCK_MODE,
    mock_blobs: mockStore.size,
  });
});

app.post('/upload', async (req: Request, res: Response) => {
  try {
    const payload = req.body;
    const serialized = JSON.stringify(payload);
    const hash = sha256(serialized);

    if (MOCK_MODE) {
      mockStore.set(hash, { content: payload, uploadedAt: Date.now() });
      return res.json({
        content_hash: '0x' + hash,
        size_bytes: serialized.length,
        backend: 'mock',
      });
    }

    const client = await getOGClient();
    const file = await client.ZgFile.fromBuffer(Buffer.from(serialized));
    const tree = await file.merkleTree();
    const rootHash = tree.rootHash();
    const tx = await client.indexer.upload(file, client.signer);
    return res.json({
      content_hash: rootHash,
      size_bytes: serialized.length,
      tx_hash: tx?.hash,
      backend: '0g',
    });
  } catch (err: any) {
    console.error('upload_failed', err);
    return res.status(500).json({ error: String(err?.message || err) });
  }
});

app.get('/download/:hash', async (req: Request, res: Response) => {
  try {
    const hash = (req.params.hash || '').replace(/^0x/, '');

    if (MOCK_MODE) {
      const blob = mockStore.get(hash);
      if (!blob) return res.status(404).json({ error: 'not_found' });
      return res.json({ content: blob.content, backend: 'mock' });
    }

    const client = await getOGClient();
    const data = await client.indexer.download('0x' + hash);
    return res.json({ content: JSON.parse(data.toString('utf-8')), backend: '0g' });
  } catch (err: any) {
    console.error('download_failed', err);
    return res.status(500).json({ error: String(err?.message || err) });
  }
});

app.get('/health', (_req: Request, res: Response) => {
  res.json({ status: 'ok', mock_mode: MOCK_MODE });
});

// ──────────────────────────────────────────────────────────────────────

app.listen(PORT, () => {
  console.log(`[sidecar-0gstorage] listening on :${PORT} (mock=${MOCK_MODE})`);
});
