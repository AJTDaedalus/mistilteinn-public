import type { components } from '../api/api.types';

export type DiscSetSummary = components['schemas']['DiscSetSummary'];

export function extractBasename(path: string | null | undefined): string | null {
  if (!path) return null;
  const parts = path.split('/');
  const filename = parts[parts.length - 1];
  const lastDot = filename.lastIndexOf('.');
  const base = lastDot === -1 ? filename : filename.substring(0, lastDot);
  return base.trim();
}

export function buildIconUrl(iconPath: string | null | undefined): string | null {
  const base = extractBasename(iconPath);
  if (!base) return null;
  return `/icons/${base}.webp`;
}

export const discSetIconUrl = buildIconUrl;
export const wEngineIconUrl = buildIconUrl;
export const agentIconUrl   = buildIconUrl;

export function specialtyIconUrl(specialty: string | null | undefined): string | null {
  if (!specialty) return null;
  const capitalized = specialty.charAt(0).toUpperCase() + specialty.slice(1).toLowerCase();
  return `/icons/Icon${capitalized}.webp`;
}

export function elementIconUrl(element: string | null | undefined): string | null {
  if (!element) return null;
  const capitalized = element.charAt(0).toUpperCase() + element.slice(1).toLowerCase();
  return `/icons/IconElement${capitalized}.webp`;
}

export function factionIconUrl(faction: string | null | undefined): string | null {
  if (!faction) return null;
  const normalized = faction
    .toLowerCase()
    .trim()
    .replace(/\s+/g, '-')
    .replace(/[^a-z0-9_.-]/g, '');
  return `/icons/IconFaction_${normalized}.webp`;
}

