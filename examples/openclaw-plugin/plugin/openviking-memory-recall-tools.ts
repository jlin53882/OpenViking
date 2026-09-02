import { Type } from "@sinclair/typebox";

import type { SearchContextEntry, SearchContextResult } from "../client.js";
import type { EffectiveQueryConfig, QueryConfigContext, RuntimeQueryParams } from "../query-config.js";
import type { RecallResourceType } from "../registries/recall-resource-types.js";
import type {
  RecallTraceEntry,
  RecallTraceResult,
} from "../recall-trace.js";

export type OpenVikingMemoryRecallToolContext = {
  sessionKey?: string;
  sessionId?: string;
  agentId?: string;
  senderId?: string;
  requesterSenderId?: string;
};

export type OpenVikingMemoryRecallSession = {
  sessionId?: string;
  sessionKey?: string;
  ovSessionId?: string;
  agentId: string;
  actorPeerId?: string;
};

export type OpenVikingMemoryRecallClient = {
  searchContext: (
    query: string,
    options: {
      sessionId?: string;
      limit?: number;
      scoreThreshold?: number;
      contextType?: string | string[];
      queryExpansion?: "off" | "auto";
      maxTokens?: number;
      detail?: "abstract" | "overview" | "full";
      peerScope?: "actor" | "all";
      actorPeerId?: string;
    },
  ) => Promise<SearchContextResult>;
  getDefaultAgentId: () => string;
};

export type OpenVikingMemoryRecallToolsDeps = {
  registerTool: (toolOrFactory: unknown, opts: { name: string }) => void;
  getClient: () => Promise<OpenVikingMemoryRecallClient>;
  queryConfigStore: {
    getEffective: (
      ctx: QueryConfigContext,
      request?: RuntimeQueryParams,
    ) => Promise<EffectiveQueryConfig>;
  };
  toQueryConfigContext: (session: OpenVikingMemoryRecallSession) => QueryConfigContext;
  resolvePluginSessionRouting: (
    ctx?: OpenVikingMemoryRecallToolContext,
  ) => OpenVikingMemoryRecallSession;
  isBypassedSession: (ctx?: OpenVikingMemoryRecallToolContext) => boolean;
  makeBypassedToolResult: (toolName: string) => unknown;
  resolveRecallSearchPlan: (
    resourceTypes: unknown,
    ctx: { ovSessionId?: string; agentId?: string },
  ) => {
    resourceTypes: RecallResourceType[];
    searches: Array<{ resourceType: RecallResourceType; contextType: "memory" | "resource" }>;
    skipped: Array<{ resourceType: RecallResourceType; reason: "missing_session" }>;
  };
  inferRecallResourceType: (uri: string) => RecallResourceType | undefined;
  createTraceId: (source: string) => string;
  boundTraceQuery: (query: string, maxChars: number) => { query: string; queryTruncated?: boolean };
  previewText: (value: unknown, maxChars: number) => string | undefined;
  traceRecorder?: { recordAndFlush?: (entry: RecallTraceEntry) => Promise<unknown> };
  cfg: {
    recallTargetTypes: RecallResourceType[];
    traceRecallMaxResultsPerSearch: number;
    traceRecallPreviewChars: number;
    traceRecallQueryMaxChars: number;
    logFindRequests: boolean;
  };
  logger: {
    info?: (message: string) => void;
  };
};

function toTraceResult(
  item: SearchContextEntry,
  deps: OpenVikingMemoryRecallToolsDeps,
): RecallTraceResult {
  const resourceType = deps.inferRecallResourceType(item.uri);
  return {
    uri: item.uri,
    resourceType,
    category: item.category,
    score: item.score,
    abstractPreview: deps.previewText(item.text, deps.cfg.traceRecallPreviewChars),
    resultType: resourceType === "resource" ? "resource" : "memory",
  };
}

const CHARS_PER_TOKEN = 4;

export function registerOpenVikingMemoryRecallTools(
  deps: OpenVikingMemoryRecallToolsDeps,
): void {
  deps.registerTool(
    (ctx: OpenVikingMemoryRecallToolContext) => ({
      name: "memory_recall",
      label: "Memory Recall (OpenViking)",
      description:
        "Search long-term memories from OpenViking. Use when you need past user preferences, facts, or decisions.",
      parameters: Type.Object({
        query: Type.String({ description: "Search query" }),
        limit: Type.Optional(
          Type.Number({ description: "Global max results (tool/config value, otherwise server default)" }),
        ),
        scoreThreshold: Type.Optional(
          Type.Number({ description: "Minimum score (0-1, default: plugin config)" }),
        ),
        resourceTypes: Type.Optional(
          Type.Array(Type.String({ description: "resource, user, or agent" })),
        ),
      }),
      async execute(_toolCallId: string, params: Record<string, unknown>) {
        if (deps.isBypassedSession(ctx)) {
          return deps.makeBypassedToolResult("memory_recall");
        }
        const session = deps.resolvePluginSessionRouting(ctx);
        const { query } = params as { query: string };
        const queryConfig = await deps.queryConfigStore.getEffective(deps.toQueryConfigContext(session), {
          recallLimit: typeof (params as { limit?: number }).limit === "number" ? (params as { limit: number }).limit : undefined,
          scoreThreshold: typeof (params as { scoreThreshold?: number }).scoreThreshold === "number" ? (params as { scoreThreshold: number }).scoreThreshold : undefined,
          resourceTypes: Object.prototype.hasOwnProperty.call(params, "resourceTypes")
            ? (params as { resourceTypes?: unknown }).resourceTypes as RuntimeQueryParams["resourceTypes"]
            : undefined,
        });
        const limit = queryConfig.recallLimit;
        const limitSource = queryConfig.sources?.recallLimit ?? "static";
        const limitConfigured = limitSource !== "default";
        const scoreThreshold = queryConfig.scoreThreshold;
        const requestedResourceTypes = Object.prototype.hasOwnProperty.call(params, "resourceTypes")
          ? (params as { resourceTypes?: unknown }).resourceTypes
          : queryConfig.resourceTypes;
        const searchPlan = deps.resolveRecallSearchPlan(requestedResourceTypes ?? deps.cfg.recallTargetTypes, {
          ovSessionId: session.ovSessionId,
          agentId: session.agentId,
        });
        if (searchPlan.searches.length === 0) {
          await deps.traceRecorder?.recordAndFlush?.({
            schemaVersion: "1.0",
            traceId: deps.createTraceId("memory_recall"),
            ts: Date.now(),
            sessionId: session.sessionId,
            sessionKey: session.sessionKey,
            ovSessionId: session.ovSessionId,
            agentId: session.agentId,
            source: "memory_recall",
            operationType: "semantic_find",
            resourceTypes: searchPlan.resourceTypes,
            trigger: deps.boundTraceQuery(query, deps.cfg.traceRecallQueryMaxChars),
            searches: searchPlan.skipped.map((skipped) => ({
              resourceType: skipped.resourceType,
              limit,
              scoreThreshold,
              durationMs: 0,
              total: 0,
              results: [],
              error: skipped.reason,
            })),
            selected: [],
            stats: { candidateCount: 0, selectedCount: 0, injectedCount: 0, estimatedTokens: 0 },
          });
          return {
            content: [{ type: "text", text: "No relevant OpenViking memories found." }],
            details: { count: 0, total: 0, scoreThreshold, limitSource },
          };
        }
        const contextTypes = [...new Set(searchPlan.searches.map((search) => search.contextType))];
        const maxTokens = Math.min(
          32_000,
          Math.max(64, Math.round(queryConfig.maxInjectedChars / CHARS_PER_TOKEN)),
        );

        const recallClient = await deps.getClient();
        if (deps.cfg.logFindRequests) {
          deps.logger.info?.(
            `openviking: memory_recall X-OpenViking-Actor-Peer="${session.actorPeerId ?? "none"}" ` +
              `(plugin defaultAgentId="${recallClient.getDefaultAgentId()}" is unused when session context is present)`,
          );
        }

        const startedAt = Date.now();
        const result = await recallClient.searchContext(query, {
          sessionId: session.ovSessionId,
          ...(limitConfigured ? { limit } : {}),
          scoreThreshold,
          contextType: contextTypes.length === 1 ? contextTypes[0] : contextTypes,
          queryExpansion: "auto",
          maxTokens,
          detail: queryConfig.recallPreferAbstract ? "abstract" : undefined,
          peerScope: "actor",
          actorPeerId: session.actorPeerId,
        });
        const durationMs = Date.now() - startedAt;
        const entries = (result.entries ?? []).filter((entry) => Boolean(entry.uri));
        const candidateCount = typeof result.stats?.candidates === "number"
          ? result.stats.candidates
          : entries.length;
        const rawRetrievalErrors = result.stats?.retrieval_errors;
        const retrievalErrors = Array.isArray(rawRetrievalErrors)
          ? rawRetrievalErrors.map((error) => String(error))
          : [];
        const memoryRecallSearches: RecallTraceEntry["searches"] = searchPlan.searches.map((search) => {
          const matching = entries.filter((entry) => {
            const isResource = deps.inferRecallResourceType(entry.uri) === "resource";
            return search.contextType === "resource" ? isResource : !isResource;
          });
          return {
            resourceType: search.resourceType,
            contextType: search.contextType,
            limit,
            scoreThreshold,
            durationMs,
            total: matching.length,
            results: matching
              .map((entry) => toTraceResult(entry, deps))
              .slice(0, deps.cfg.traceRecallMaxResultsPerSearch),
            error: retrievalErrors.length > 0 ? retrievalErrors.join("; ") : undefined,
          };
        });
        const rendered = result.digest?.trim() || result.rendered?.trim() || "";
        const displayedUris = new Set(rendered ? entries.map((entry) => entry.uri) : []);
        const memories = entries.map((entry) => ({
          uri: entry.uri,
          category: entry.category,
          score: entry.score,
          abstract: entry.text,
        }));
        const recordMemoryRecallTrace = async (injectedUris: Set<string>) => {
          await deps.traceRecorder?.recordAndFlush?.({
            schemaVersion: "1.0",
            traceId: deps.createTraceId("memory_recall"),
            ts: Date.now(),
            sessionId: session.sessionId,
            sessionKey: session.sessionKey,
            ovSessionId: session.ovSessionId,
            agentId: session.agentId,
            source: "memory_recall",
            operationType: "semantic_find",
            resourceTypes: searchPlan.resourceTypes,
            trigger: deps.boundTraceQuery(query, deps.cfg.traceRecallQueryMaxChars),
            searches: memoryRecallSearches,
            selected: entries.map((entry) => ({
              uri: entry.uri,
              resourceType: deps.inferRecallResourceType(entry.uri),
              category: entry.category,
              score: entry.score,
              abstractPreview: deps.previewText(entry.text, deps.cfg.traceRecallPreviewChars),
              injected: injectedUris.has(entry.uri),
              displayed: injectedUris.has(entry.uri),
            })),
            stats: {
              candidateCount,
              selectedCount: entries.length,
              injectedCount: injectedUris.size,
              estimatedTokens: typeof result.stats?.used_tokens === "number"
                ? result.stats.used_tokens
                : undefined,
            },
          });
        };
        if (entries.length === 0 || !rendered) {
          await recordMemoryRecallTrace(new Set());
          return {
            content: [{ type: "text", text: "No relevant OpenViking memories found." }],
            details: { count: 0, total: candidateCount, scoreThreshold, limitSource },
          };
        }
        await recordMemoryRecallTrace(displayedUris);
        return {
          content: [{ type: "text", text: rendered }],
          details: {
            count: entries.length,
            memories,
            total: candidateCount,
            scoreThreshold,
            requestLimit: limitConfigured ? limit : undefined,
            limitSource,
            recallMaxInjectedChars: queryConfig.maxInjectedChars,
          },
        };
      },
    }),
    { name: "memory_recall" },
  );
}
