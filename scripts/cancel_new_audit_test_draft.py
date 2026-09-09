"""取消当前东莞联调产生的未完成新增草稿，绝不发起审核。"""

from pathlib import Path
import json
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.browser import BrowserConfig, BrowserSession, is_new_audit_qualification_detail_url
from src.input_loader import load_input
from src.new_audit_qualification import NewAuditQualificationPage
from src.run_logging import application_data_dir
from src.workflow import WorkflowConfig, WorkflowRunner


class DraftCanceller(WorkflowRunner):
    def _run_industry_qualification(self, page, company):
        view = NewAuditQualificationPage(page, timeout=60_000)
        add = view._wait_for_unique_visible(
            page.get_by_role('button', name='新增资质', exact=True),
            '新增资质', timeout=120_000,
        )
        add.click()
        view._wait_until(view._is_new_audit_add_page, '新增页未加载', timeout=60_000)
        view._wait_until(lambda: bool(view._business_tabs()), '草稿业务未加载')
        promotion = view._business_container(1)
        if (
            promotion is None
            or not view._business_type_matches(promotion, '推广审查')
            or len(view._file_inputs_in(promotion)) != 2
        ):
            raise RuntimeError('Current add-page draft does not match the known two-card test draft')
        cancel = view._unique_visible(
            page.get_by_role('button', name='取消', exact=True), '取消按钮'
        )
        cancel.click()
        dialogs = view._visible(page.get_by_role('dialog'))
        for dialog in dialogs:
            if re.search(r'确认.*取消|是否.*取消|放弃', dialog.inner_text()):
                view._unique_visible(
                    dialog.get_by_role('button', name=re.compile(r'确定|确认')),
                    '取消确认按钮',
                ).click()
                break
        view._wait_until(
            lambda: is_new_audit_qualification_detail_url(page.url),
            '取消后未返回投放资质详情页', timeout=60_000,
        )
        print('Test draft cancelled; final review was not triggered.', flush=True)
        return False, False, None


def main():
    company_dir = Path('input') / '东莞山虞医药有限公司'
    result = json.loads(
        (company_dir / 'qualification-submit-result.json').read_text(encoding='utf-8')
    )
    if (
        result.get('final_submission_success') is not False
        or result.get('error') not in {
            '业务“推广审查”第1个资质卡片数量异常：期望 1，实际 2',
            '新增页存在非空补充资质草稿，拒绝自动覆盖',
        }
    ):
        raise RuntimeError('Submission result does not identify the known two-card test draft')
    company = next(
        c for c in load_input(Path('input'))
        if c.company_name == '东莞山虞医药有限公司'
    )
    config = BrowserConfig(auth_state_path=application_data_dir() / 'auth' / 'storage_state.json')
    with BrowserSession(config) as session:
        session.context.route('**/permit/web/permit/submitall', lambda route: route.abort())
        DraftCanceller(session, WorkflowConfig(final_submit=False, page_timeout_ms=60_000)).run_company(company)


if __name__ == '__main__':
    main()
