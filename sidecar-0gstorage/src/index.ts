/**
 * SibylFi 0G Storage sidecar.
 *
 * Wraps @0gfoundation/0g-storage-ts-sdk and exposes a small HTTP API that the
 * Python agents call as a local dependency on port 7000.
 *
 * In MOCK_MODE, the sidecar stores blobs in an in-memory Map keyed by SHA-256
 * hash. This lets the full pipeline run offline.
 */
import express, { Request, Response } from 'express';
import { createHash, randomUUID } from 'crypto';
import { readFile, unlink } from 'fs/promises';
import { tmpdir } from 'os';
import { join } from 'path';

const PORT = Number(process.env.PORT || 7000);
const MOCK_MODE = process.env.MOCK_MODE !== '0';
const FALLBACK_PRIVATE_KEY = '0x' + '00'.repeat(32);

const app = express();
app.use(express.json({ limit: '10mb' }));

const mockStore = new Map<string, { content: unknown; uploadedAt: number }>();

function sha256(payload: string): string {
  return createHash('sha256').update(payload).digest('hex');
}

type OgClient = {
  MemData: new (data: Buffer) => {
    merkleTree: () => Promise<[unknown, unknown]>;
  };
  // The 0G SDK owns the exact upload/download types; keep the sidecar boundary small.
  indexer: any;
  rpcUrl: string;
  signer: unknown;
};

let ogClient: OgClient | null = null;

async function getOGClient(): Promise<OgClient> {
  if (ogClient) return ogClient;
  if (MOCK_MODE) {
    throw new Error('not_in_mock_mode');
  }

  const { Indexer, MemData } = await import('@0gfoundation/0g-storage-ts-sdk');
  const { ethers } = await import('ethers');

  const rpcUrl = process.env.OG_GALILEO_RPC || 'https://evmrpc-testnet.0g.ai';
  const indexerUrl = process.env.OG_INDEXER_URL || 'https://indexer-storage-testnet-turbo.0g.ai';
  const provider = new ethers.JsonRpcProvider(rpcUrl);
  const signer = new ethers.Wallet(process.env.OG_BROKER_KEY || FALLBACK_PRIVATE_KEY, provider);
  const indexer = new Indexer(indexerUrl);

  const client = { MemData, indexer, rpcUrl, signer };
  ogClient = client;
  return client;
}

function rootHashFromTree(tree: unknown): unknown {
  if (tree && typeof tree === 'object' && 'rootHash' in tree) {
    const rootHash = (tree as { rootHash: unknown }).rootHash;
    return typeof rootHash === 'function' ? rootHash() : rootHash;
  }
  return undefined;
}

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
    const data = new client.MemData(Buffer.from(serialized));
    const [tree, treeErr] = await data.merkleTree();
    if (treeErr !== null) throw new Error(`Merkle tree error: ${treeErr}`);

    const [tx, uploadErr] = await client.indexer.upload(data, client.rpcUrl, client.signer);
    if (uploadErr !== null) throw new Error(`Upload error: ${uploadErr}`);

    return res.json({
      content_hash: tx?.rootHash ?? rootHashFromTree(tree),
      size_bytes: serialized.length,
      tx_hash: tx?.txHash,
      backend: '0g',
    });
  } catch (err: unknown) {
    console.error('upload_failed', err);
    return res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
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
    const outputPath = join(tmpdir(), `sibylfi-0g-${randomUUID()}.json`);

    try {
      const downloadErr = await client.indexer.download('0x' + hash, outputPath, true);
      if (downloadErr !== null && downloadErr !== undefined) {
        throw new Error(`Download error: ${downloadErr}`);
      }

      const raw = await readFile(outputPath, 'utf8');
      return res.json({ content: JSON.parse(raw), backend: '0g' });
    } finally {
      await unlink(outputPath).catch(() => undefined);
    }
  } catch (err: unknown) {
    console.error('download_failed', err);
    return res.status(500).json({ error: err instanceof Error ? err.message : String(err) });
  }
});

app.get('/health', (_req: Request, res: Response) => {
  res.json({ status: 'ok', mock_mode: MOCK_MODE });
});

app.listen(PORT, () => {
  console.log(`[sidecar-0gstorage] listening on :${PORT} (mock=${MOCK_MODE})`);
});
