import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';

import { API_BASE_URL } from '../../api/api.client';
import { CombosService } from './combos.service';

function setupSvc() {
  TestBed.configureTestingModule({
    providers: [{ provide: API_BASE_URL, useValue: 'http://test' }],
  });
  return TestBed.inject(CombosService);
}

function mockResponse<T>(payload: T, status = 200): typeof globalThis.fetch {
  return vi.fn(async () =>
    new Response(JSON.stringify(payload), {
      status,
      headers: { 'content-type': 'application/json' },
    }),
  );
}

describe('CombosService', () => {
  it('listForBuild() filters by build_id query param', async () => {
    const fetchSpy = vi.fn<typeof globalThis.fetch>(
      async () =>
        new Response(JSON.stringify({
          items: [{
            id: 'c1', name: 'BA1 → EX', build_id: 'b1',
            sequence: [], description: '',
          }],
          total: 1, offset: 0, limit: 200,
        }), { status: 200, headers: { 'content-type': 'application/json' } }),
    );
    globalThis.fetch = fetchSpy;
    const svc = setupSvc();
    const out = await svc.listForBuild('b1');
    expect(out).toHaveLength(1);
    const url = (fetchSpy.mock.calls[0][0] as Request).url;
    expect(url).toContain('build_id=b1');
  });

  it('create() sends build_id + sequence', async () => {
    const created = {
      id: 'c1', name: 'My Combo', build_id: 'b1',
      sequence: [{ attack_id: 'atk1', label: 'BA1' }], description: '',
    };
    const fetchSpy = vi.fn<typeof globalThis.fetch>(
      async () =>
        new Response(JSON.stringify(created), {
          status: 201,
          headers: { 'content-type': 'application/json' },
        }),
    );
    globalThis.fetch = fetchSpy;
    const svc = setupSvc();
    const out = await svc.create({
      name: 'My Combo', team_id: 'b1',
      sequence: [{ attack_id: 'atk1', label: 'BA1' }],
    });
    expect(out.id).toBe('c1');
    const req = fetchSpy.mock.calls[0][0] as Request;
    const body = await req.json();
    expect(body.team_id).toBe('b1');
    expect(body.sequence[0].attack_id).toBe('atk1');
  });

  it('update() PATCHes the combo', async () => {
    const fetchSpy = vi.fn<typeof globalThis.fetch>(
      async () =>
        new Response(JSON.stringify({
          id: 'c1', name: 'New name', build_id: 'b1',
          sequence: [], description: '',
        }), { status: 200, headers: { 'content-type': 'application/json' } }),
    );
    globalThis.fetch = fetchSpy;
    const svc = setupSvc();
    await svc.update('c1', { name: 'New name' });
    expect((fetchSpy.mock.calls[0][0] as Request).method).toBe('PATCH');
  });

  it('remove() DELETEs', async () => {
    const fetchSpy = vi.fn<typeof globalThis.fetch>(
      async () => new Response(null, { status: 204 }),
    );
    globalThis.fetch = fetchSpy;
    const svc = setupSvc();
    await svc.remove('c1');
    expect((fetchSpy.mock.calls[0][0] as Request).method).toBe('DELETE');
  });

  it('listForTeam() filters by team_id query param', async () => {
    const fetchSpy = vi.fn<typeof globalThis.fetch>(
      async () =>
        new Response(JSON.stringify({
          items: [{ id: 'c1', name: 'R1', team_id: 't1', sequence: [], description: '' }],
          total: 1, offset: 0, limit: 200,
        }), { status: 200, headers: { 'content-type': 'application/json' } }),
    );
    globalThis.fetch = fetchSpy;
    const svc = setupSvc();
    const out = await svc.listForTeam('t1');
    expect(out).toHaveLength(1);
    const url = (fetchSpy.mock.calls[0][0] as Request).url;
    expect(url).toContain('team_id=t1');
  });

  it('evaluateTeam() POSTs to team calculate endpoint and returns response', async () => {
    const mockResult = {
      team_id: 't1', team_name: 'T', dps_build_id: 'b1',
      dps_agent_name: 'DPS', combo_id: 'c1', combo_name: 'R',
      enemy_name: 'Dummy', auto_conditions: [], applied_team_buffs: [],
      by_agent: [{ agent_name: 'DPS', build_id: 'b1', damage: 100000, pct: 100 }],
      total_damage: 100000, standard_total: 100000, anomaly_total: 0,
      steps: [], by_category: [], by_element: [],
      total_atk: 3000, total_crit_rate: 500, total_crit_dmg: 5000, total_pen_ratio: 0,
    };
    const fetchSpy = vi.fn<typeof globalThis.fetch>(
      async () => new Response(JSON.stringify(mockResult), {
        status: 200, headers: { 'content-type': 'application/json' },
      }),
    );
    globalThis.fetch = fetchSpy;
    const svc = setupSvc();
    const result = await svc.evaluateTeam('t1', {
      combo_id: 'c1',
      enemy_profile_id: 'e1',
      refinement: 1,
      crit_mode: 'expected',
      is_stunned: false,
      stun_dmg_mult: 15000,
      with_attribution: false,
    });
    expect(result.total_damage).toBe(100000);
    expect(result.by_agent).toHaveLength(1);
    expect(result.by_agent![0].agent_name).toBe('DPS');
    const req = fetchSpy.mock.calls[0][0] as Request;
    expect(req.method).toBe('POST');
    expect(req.url).toContain('/api/v1/teams/t1/calculate');
  });

  it('getAgentAttacks() returns the embedded attacks array', async () => {
    globalThis.fetch = mockResponse({
      id: 'a1', name: 'Caesar', hakushin_id: 1, full_name: 'Caesar',
      element: 'physical', specialty: 'stun', rarity: 'S', faction: 'x',
      faction_id: 0, base_hp: 0, base_atk: 0, base_def: 0,
      base_crit_rate: 0, base_crit_dmg: 0, base_anomaly_mastery: 0,
      base_anomaly_proficiency: 0, base_pen_flat: 0, base_pen_ratio: 0,
      base_impact: 0, base_impact_pct: 0, base_energy_regen: 0,
      level_curves: {}, image_url: '',
      attacks: [
        { id: 'atk1', skill_key: 'Basic', name: 'Basic 1', hit_index: 0,
          element: 'physical', damage_base: 10000, damage_growth: 500,
          agent_id: 'a1', hakushin_skill_id: 1 },
        { id: 'atk2', skill_key: 'Ultimate', name: 'Ultimate', hit_index: 0,
          element: 'physical', damage_base: 60000, damage_growth: 3000,
          agent_id: 'a1', hakushin_skill_id: 5 },
      ],
      passives: [], mindscapes: [],
    });
    const svc = setupSvc();
    const attacks = await svc.getAgentAttacks('a1');
    expect(attacks).toHaveLength(2);
    expect(attacks[0].name).toBe('Basic 1');
  });
});
