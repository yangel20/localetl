import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { IDS, pipeline, source } from '../../app/api/fixtures';
import { ApiError } from '../../app/api/errors';
import { createMockFetch, errorResponse } from '../../app/api/mockFetch';
import type { PipelineCreate } from '../../app/api/types';
import { moveItem } from './configModel';
import { emptyDraft, PipelineForm, type PipelineDraft } from './PipelineForm';

type Overrides = Parameters<typeof createMockFetch>[0];
const json = (b: unknown) => new Response(JSON.stringify(b), { headers: { 'Content-Type': 'application/json' } });

function setup(initial: PipelineDraft, overrides: Overrides = {}, onSave = vi.fn(async (_b: PipelineCreate) => {})) {
  const fetchMock = vi.fn(createMockFetch(overrides));
  vi.stubGlobal('fetch', fetchMock);
  render(<PipelineForm initial={initial} sources={[source]} onSave={onSave} />);
  return { onSave, fetchMock };
}
const existing = (): PipelineDraft => ({
  name: pipeline.name,
  description: '',
  source_id: IDS.source,
  config: structuredClone(pipeline.config),
});

afterEach(() => vi.unstubAllGlobals());

describe('building from a source', () => {
  it('fills columns from the source and offers only the 7 operations and 6 rules', async () => {
    setup(emptyDraft());
    await userEvent.selectOptions(screen.getByLabelText('Data source'), 'orders');
    expect(screen.getByLabelText('Name for order_id')).toHaveValue('order_id');
    expect(screen.getByLabelText('Type for amount')).toHaveValue('float');
    const ops = within(screen.getByLabelText('Add transformation')).getAllByRole('option').slice(1);
    expect(ops).toHaveLength(7);
    const rules = within(screen.getByLabelText('Add validation')).getAllByRole('option').slice(1);
    expect(rules).toHaveLength(6);
  });

  it('saves a valid config built through the UI', async () => {
    const { onSave } = setup(emptyDraft());
    await userEvent.type(screen.getByLabelText('Name'), 'My pipeline');
    await userEvent.selectOptions(screen.getByLabelText('Data source'), 'orders');
    await userEvent.type(screen.getByLabelText('Target table'), 'orders_out');
    await userEvent.selectOptions(screen.getByLabelText('Add transformation'), 'trim_whitespace');
    await userEvent.selectOptions(screen.getByLabelText('Add validation'), 'not_null');
    await userEvent.click(screen.getByRole('button', { name: 'Save pipeline' }));
    expect(onSave).toHaveBeenCalledTimes(1);
    const body = onSave.mock.calls[0]![0];
    expect(body.name).toBe('My pipeline');
    expect(body.source_id).toBe(IDS.source);
    expect(body.config.target).toEqual({ table: 'orders_out', mode: 'replace' });
    expect(body.config.transformations).toEqual([{ op: 'trim_whitespace', columns: ['customer'] }]); // first string column
    expect(body.config.validations).toEqual([{ rule: 'not_null', column: 'order_id' }]);
  });
});

describe('client checks', () => {
  it('blocks saving and shows errors at their JSON Pointer path', async () => {
    const { onSave } = setup(emptyDraft());
    await userEvent.type(screen.getByLabelText('Name'), 'p');
    await userEvent.selectOptions(screen.getByLabelText('Data source'), 'orders');
    await userEvent.type(screen.getByLabelText('Target table'), 'Bad-Name');
    await userEvent.click(screen.getByRole('button', { name: 'Save pipeline' }));
    expect(onSave).not.toHaveBeenCalled();
    const alert = document.querySelector('[data-path="/target/table"]')!;
    expect(alert).toHaveTextContent(/lowercase letters/);
    expect(alert).toHaveTextContent('/target/table');
  });

  it('rule 7: a format is dropped when the type no longer allows it', async () => {
    setup({ ...existing(), config: { ...existing().config, columns: [{ source: 'd', name: 'd', type: 'date', format: '%d/%m/%Y' }], transformations: [], validations: [] } });
    expect(screen.getByLabelText('Date format for d')).toHaveValue('%d/%m/%Y');
    await userEvent.selectOptions(screen.getByLabelText('Type for d'), 'string');
    expect(screen.queryByLabelText('Date format for d')).toBeNull();
  });

  it('explains a time directive in a date format', async () => {
    setup({ ...existing(), config: { ...existing().config, columns: [{ source: 'd', name: 'd', type: 'date' }], transformations: [], validations: [] } });
    await userEvent.type(screen.getByLabelText('Date format for d'), '%Y %H');
    expect(screen.getByText(/may not contain time directives/)).toBeInTheDocument();
  });

  it('types fill_null values for the column (number, not text)', async () => {
    const { onSave } = setup(existing());
    await userEvent.selectOptions(screen.getByLabelText('Add transformation'), 'fill_null');
    // first column is order_id (integer)
    const input = screen.getByLabelText('Fill value');
    await userEvent.clear(input);
    await userEvent.type(input, 'abc');
    expect(screen.getByText('Enter a whole number.')).toBeInTheDocument();
    await userEvent.clear(input);
    await userEvent.type(input, '7');
    await userEvent.click(screen.getByRole('button', { name: 'Save pipeline' }));
    const t = onSave.mock.calls[0]![0].config.transformations!;
    expect(t.at(-1)).toEqual({ op: 'fill_null', column: 'order_id', value: 7 });
  });
});

describe('reordering', () => {
  it('moveItem reorders immutably', () => {
    const a = [1, 2, 3];
    expect(moveItem(a, 0, 2)).toEqual([2, 3, 1]);
    expect(moveItem(a, 2, 1)).toEqual([1, 3, 2]);
    expect(moveItem(a, 0, 5)).toEqual([1, 2, 3]);
    expect(a).toEqual([1, 2, 3]);
  });

  it('moves transformations with the up/down buttons and saves that order', async () => {
    const draft = existing();
    draft.config.transformations = [
      { op: 'trim_whitespace', columns: ['customer'] },
      { op: 'round_number', column: 'amount', decimals: 3 },
    ];
    const { onSave } = setup(draft);
    expect(screen.getByRole('button', { name: 'Move transformation 1 up' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Move transformation 1 down' }));
    const items = screen.getAllByRole('listitem').filter((li) => li.getAttribute('aria-label')?.startsWith('Transformation'));
    expect(items[0]).toHaveAccessibleName(/Round numbers/);
    expect(within(items[0]!).getByLabelText('Decimal places (0–10)')).toHaveValue(3);
    await userEvent.click(screen.getByRole('button', { name: 'Save pipeline' }));
    expect(onSave.mock.calls[0]![0].config.transformations!.map((t) => t.op)).toEqual(['round_number', 'trim_whitespace']);
  });
});

describe('server validation', () => {
  it('shows server errors at their paths, stripping the /config prefix', async () => {
    let sent: unknown;
    setup(existing(), {
      'POST /pipelines/validate': ({ body }) => {
        sent = body;
        return json({ valid: false, errors: [{ path: '/config/validations/0/column', message: 'unknown column' }] });
      },
    });
    await userEvent.click(screen.getByRole('button', { name: 'Validate' }));
    const at = await vi.waitFor(() => {
      const el = document.querySelector('[data-path="/validations/0"]');
      if (!el) throw new Error('not yet');
      return el;
    });
    expect(at).toHaveTextContent('unknown column');
    expect(sent).toMatchObject({ source_id: IDS.source });
  });

  it('reports a valid config', async () => {
    setup(existing());
    await userEvent.click(screen.getByRole('button', { name: 'Validate' }));
    expect(await screen.findByText('The configuration is valid.')).toBeInTheDocument();
  });

  it('maps a 422 on save back to the form', async () => {
    const onSave = vi.fn(async () => {
      throw new ApiError(422, 'validation_error', 'Invalid pipeline', [{ path: '/config/target/table', message: 'reserved name' }]);
    });
    setup(existing(), {}, onSave);
    await userEvent.click(screen.getByRole('button', { name: 'Save pipeline' }));
    expect(await screen.findByText('Invalid pipeline')).toBeInTheDocument();
    expect(document.querySelector('[data-path="/target/table"]')).toHaveTextContent('reserved name');
  });

  it('shows a transport failure from validate', async () => {
    setup(existing(), { 'POST /pipelines/validate': () => errorResponse(500, 'internal_error', 'Server exploded') });
    await userEvent.click(screen.getByRole('button', { name: 'Validate' }));
    expect(await screen.findByText('Server exploded')).toBeInTheDocument();
  });
});
