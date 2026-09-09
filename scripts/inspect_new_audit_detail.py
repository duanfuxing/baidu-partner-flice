"""只读检查新版投放资质详情已有记录，不进入新增表单。"""

from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.browser import BrowserConfig, BrowserSession
from src.input_loader import load_input
from src.run_logging import application_data_dir
from src.workflow import WorkflowConfig, WorkflowRunner
from src.type_mapping import mapping_for_input


class DetailInspector(WorkflowRunner):
    def _run_industry_qualification(self, page, company):
        try:
            page.get_by_text('已备案业务资质', exact=True).click(timeout=10_000)
            page.wait_for_timeout(1_000)
        except Exception:
            pass
        print({
            'visibleRows': len([row for row in page.locator('tr').all() if row.is_visible()]),
            'zeroBusiness': page.get_by_text('共 0 个业务资质', exact=True).count(),
        }, flush=True)
        known_types = []
        for qualification_type in company.qualification_types:
            mapping = mapping_for_input(qualification_type.type_name)
            known_types.append((qualification_type.type_name, mapping.page_names))
        for index in range(page.locator('tr').count()):
            row = page.locator('tr').nth(index)
            if not row.is_visible():
                continue
            matched = [
                input_name
                for input_name, aliases in known_types
                if any(row.get_by_text(alias, exact=True).count() for alias in aliases)
            ]
            if matched:
                print('KNOWN_ROW', {
                    'row': index,
                    'types': matched,
                    'saved': bool(row.get_by_text('已保存待送审', exact=True).count()),
                    'edit': bool(row.get_by_role('button', name='修改', exact=True).count()),
                }, flush=True)
        for index in range(page.locator('tr').count()):
            row = page.locator('tr').nth(index)
            if row.is_visible() and '推广审查' in row.inner_text():
                print({
                    'row': index,
                    'promotionExact': row.get_by_text('推广审查', exact=True).count(),
                    'savedExact': row.get_by_text('已保存待送审', exact=True).count(),
                    'editButtonExact': row.get_by_role('button', name='修改', exact=True).count(),
                    'editTextExact': row.get_by_text('修改', exact=True).count(),
                    'tags': row.locator('*').evaluate_all(
                        "els => els.filter(e => ['推广审查','已保存待送审','修改'].includes(e.textContent.trim())).map(e => ({tag:e.tagName,class:e.className,role:e.getAttribute('role')}))"
                    ),
                }, flush=True)
        rows = page.locator('tr').filter(has=page.get_by_text('推广审查', exact=True))
        if rows.count() == 1:
            batches = [
                button for button in page.get_by_role('button', name='批量操作', exact=True).all()
                if button.is_visible()
            ]
            if len(batches) == 1:
                batches[0].click()
                page.wait_for_timeout(500)
                print('BATCH_MENU', page.locator('body').evaluate("""body =>
                  [...body.querySelectorAll('[role=menuitem], .el-dropdown-menu__item')]
                    .filter(e => e.getClientRects().length)
                    .map(e => e.innerText.trim()).filter(Boolean)
                """), flush=True)
                page.keyboard.press('Escape')
            edit = rows.first.get_by_role('button', name='修改', exact=True)
            action = edit if edit.count() else rows.first.get_by_role('button', name='推广审查', exact=True)
            action.click()
            try:
                page.get_by_text('编辑投放资质', exact=True).wait_for(state='visible', timeout=30_000)
                page.locator('input[type=file]').first.wait_for(state='attached', timeout=30_000)
            except Exception:
                print('ROW_ACTION_RESULT', {'editable': False, 'fileInputs': page.locator('input[type=file]').count()}, flush=True)
                return False, False, None
            first_file = page.locator('input[type=file]').first
            form = first_file.locator("xpath=ancestor::*[.//*[normalize-space(.)='举证链接']][1]")
            expected_evidence = [
                qualification.evidence_url or ''
                for item in company.qualification_types
                if item.type_name == '推广审查'
                for qualification in item.qualifications
            ]
            input_structure = page.locator('input[type=file]').evaluate_all("""(inputs, expected) => inputs.map((input, index) => {
              const ancestors = [];
              for (let node = input.parentElement; node && ancestors.length < 10; node = node.parentElement) {
                const classes = String(node.className || '');
                if (classes.includes('form-card') || classes.includes('supp') || classes.includes('reserve')) {
                  ancestors.push({tag: node.tagName, classes});
                }
              }
              const nearest = input.closest('.form-card');
              const evidence = nearest ? [...nearest.querySelectorAll('input')]
                .find(item => item.type !== 'file') : null;
              const actual = evidence ? evidence.value.trim() : '';
              const wanted = expected[index] || '';
              return {
                index,
                nearestClass: nearest ? nearest.className : null,
                previewCounts: nearest ? [...nearest.querySelectorAll('.file-count')].map(e => e.innerText.trim()) : [],
                deleteCount: nearest ? nearest.querySelectorAll('.delete-btn').length : 0,
                saveStatus: nearest ? [...nearest.querySelectorAll('*')]
                  .map(e => e.textContent.trim()).find(text => text === '已保存待送审' || text === '待保存') : null,
                evidenceExact: actual === wanted,
                evidenceEquivalentWithoutEmptyFragment:
                  actual.replace(/#$/, '') === wanted.replace(/#$/, ''),
                evidencePresent: Boolean(actual),
                ancestors,
              };
            })""", expected_evidence)
            print('ROW_ACTION_RESULT', {
                'editable': True,
                'fileInputs': page.locator('input[type=file]').count(),
                'mainImageDeletes': form.locator('.delete-btn').count(),
                'inputs': input_structure,
            }, flush=True)
        return False, False, None


def main():
    companies = load_input(Path('input'))
    company = next(c for c in companies if c.company_name == '东莞山虞医药有限公司')
    config = BrowserConfig(auth_state_path=application_data_dir() / 'auth' / 'storage_state.json')
    with BrowserSession(config) as session:
        DetailInspector(session, WorkflowConfig(final_submit=False, page_timeout_ms=60_000)).run_company(company)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Detail inspection stopped: {type(exc).__name__}', flush=True)
        sys.exit(1)
