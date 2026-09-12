"""人工监督的单资质诊断；默认先只读检查，标准输入命令控制后续采集。"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime
import hashlib
import importlib
import json
import logging
from pathlib import Path
import re
import select
import sys
import time
import traceback
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.qualification_trace import NetworkTrace
import src.new_audit_qualification as new_audit_module
from src.browser import BrowserConfig, BrowserSession, is_new_audit_qualification_detail_url
from src.errors import PageFlowError
from src.input_loader import load_input
from src.new_audit_qualification import NewAuditQualificationPage, evidence_urls_match
from src.run_logging import application_data_dir
from src.upload_identity import preview_files, verify_preview_content
from src.workflow import WorkflowConfig, WorkflowRunner, select_url_and_open_industry_qualification


class ObservedPage(NewAuditQualificationPage):
    def __init__(self, page, trace, timeout):
        super().__init__(page, timeout=timeout)
        self.trace = trace

    def _save_qualification_card(self, *args, **kwargs):
        self.trace.mark('page_card_save_method')
        result = super()._save_qualification_card(*args, **kwargs)
        self.trace.mark('page_card_save_response_validated')
        return result

    def _wait_for_card_save_settle(self, *args, **kwargs):
        self.trace.mark('wait_card_settle')
        result = super()._wait_for_card_save_settle(*args, **kwargs)
        self.trace.mark('card_settled')
        return result

    def _verify_file_receipts(self, *args, **kwargs):
        previous = self.trace.phase
        if kwargs.get('content'):
            self.trace.mark('agent_content_verification')
        try:
            return super()._verify_file_receipts(*args, **kwargs)
        finally:
            if kwargs.get('content'):
                self.trace.mark(previous)


class LifecycleRunner(WorkflowRunner):
    def __init__(self, session, config, trace, qualification_type, qualification):
        super().__init__(session, config)
        self.trace = trace
        self.target_type = replace(qualification_type, qualifications=(qualification,))
        self.qualification = qualification
        self.allow_writes = False
        self.upload_completed = False
        self.page = None

    def guard(self, route):
        path = urlsplit(route.request.url).path.rstrip('/')
        endpoint = path.rsplit('/', 1)[-1].lower()
        prohibited = endpoint == 'submitall' or (
            not self.allow_writes and re.search(r'submit|save|delete|remove|cancel|dellice', endpoint)
        )
        if prohibited:
            self.trace.emit('blocked_write', url=self.trace.redactor.url(route.request.url))
            route.abort()
        else:
            route.continue_()

    def card(self):
        return self.view._upload_container(self.view._file_inputs_in(self.page)[0])

    def inspect(self):
        cards = self.view._file_inputs_in(self.page)
        result = []
        for index, file_input in enumerate(cards):
            card = self.view._upload_container(file_input)
            files = preview_files(card)
            fields = self.view._visible(card.locator('input:not([type=file])'))
            result.append({'index': index, 'file_count': len(files),
                           'ready_count': sum(f['ready'] for f in files),
                           'evidence_present': any(f.input_value() for f in fields),
                           'saved_status': bool(self.view._visible(card.get_by_text('已保存待送审', exact=True)))})
        self.trace.emit('inspection', cards=result)
        print('CARDS', json.dumps(result, ensure_ascii=False), flush=True)
        return result

    def upload_empty(self):
        self.inspect()
        if preview_files(self.card()):
            raise PageFlowError('target-card-not-empty')
        # Restrict the production upload loop to the first card, leaving other cards intact.
        self.allow_writes = True
        self.trace.mark('before_first_file')
        self.view._upload_type_in(self.target_type, 0, self.card)
        self.upload_completed = True
        self.trace.mark('qualification_upload_completed')
        self.page.wait_for_timeout(5000)
        self.inspect()

    def verify(self):
        if not self.upload_completed:
            raise PageFlowError('no-completed-upload-to-verify')
        receipts = self.view._saved_file_receipts.get((0, 0), ())
        if len(receipts) != len(self.qualification.files):
            raise PageFlowError('missing-upload-receipts')
        self.allow_writes = False
        self.trace.mark('reopen_saved_detail')
        # A reload obtains persisted data using the same dynamically supplied edit URL.
        self.page.reload(wait_until='domcontentloaded', timeout=self.config.page_timeout_ms)
        self.page.locator('input[type=file]').first.wait_for(state='attached', timeout=self.config.page_timeout_ms)
        self.view._verify_file_receipts(self.card, receipts, 'target', content=True)
        field = self.view._unique_visible(self.card().locator('input:not([type=file])'), '举证链接')
        if not evidence_urls_match(field.input_value(), self.qualification.evidence_url or ''):
            raise PageFlowError('persisted-evidence-mismatch')
        self.trace.mark('persisted_qualification_verified')
        self.trace.emit('verification', file_count=len(receipts), files=[{
            'file_ref': self.trace.redactor.alias(r.server_id), 'sha256': r.sha256
        } for r in receipts], evidence_matches=True)
        print('PERSISTENCE_VERIFIED', len(receipts), flush=True)

    def _run_industry_qualification(self, page, company):
        if not is_new_audit_qualification_detail_url(page.url):
            raise PageFlowError('legacy-page-deprecated')
        self.page = page
        self.detail_url = page.url
        self.view = ObservedPage(page, self.trace, self.config.page_timeout_ms)
        self.trace.mark('open_saved_promotion')
        if not self.view._open_saved_promotion_for_edit():
            print('NO_SAVED_PROMOTION', flush=True)
            return False, False, None
        self.trace.mark('inspect_target_before_upload')
        self.inspect()
        return False, False, None

    def command_loop(self):
        print('READY commands: page-state, inspect, open-new, upload-empty, verify, resume-navigation, finish', flush=True)
        while self.session.browser.is_connected():
            pages = [p for p in self.session.context.pages if not p.is_closed()]
            if not pages:
                break
            pages[0].wait_for_timeout(250)
            if not select.select([sys.stdin], [], [], 0)[0]:
                continue
            command = sys.stdin.readline().strip()
            if command == 'finish':
                break
            try:
                if command == 'inspect':
                    self.inspect()
                elif command == 'upload-empty':
                    self.upload_empty()
                elif command == 'verify':
                    self.verify()
                else:
                    # Reload only diagnostic actions, preserving the same browser and trace.
                    from scripts import lifecycle_actions
                    importlib.reload(lifecycle_actions).execute(self, command)
            except Exception as exc:
                self.allow_writes = False
                self.trace.emit('operation_error', error_type=type(exc).__name__, error_ref=self.trace.redactor.alias(str(exc)),
                                sites=[{'module': Path(f.filename).name, 'line': f.lineno, 'function': f.name}
                                       for f in traceback.extract_tb(exc.__traceback__)])
                print('OPERATION_ERROR', type(exc).__name__, flush=True)
            print('READY', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, default=Path('input'))
    parser.add_argument('--company')
    parser.add_argument('--directory', default='资质1')
    parser.add_argument('--timeout', type=int, default=120)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    companies = load_input(args.input)
    candidates = [c for c in companies if args.company is None or c.company_name == args.company]
    if len(candidates) != 1:
        raise ValueError('select-exactly-one-company')
    company = candidates[0]
    target_type = next(t for t in company.qualification_types if t.type_name == '推广审查')
    qualification = next(q for q in target_type.qualifications if q.index_name == args.directory)
    if args.directory != target_type.qualifications[0].index_name:
        raise ValueError('only-first-directory-supported-by-this-inspector')
    output = args.output or Path('logs') / ('qualification-trace-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    trace = NetworkTrace(output)
    # Do not send ordinary workflow logs containing free server messages to this transcript.
    logging.getLogger().addHandler(logging.NullHandler())
    logging.getLogger().setLevel(logging.CRITICAL)
    config = BrowserConfig(auth_state_path=application_data_dir() / 'auth/storage_state.json', timeout_ms=args.timeout*1000)
    print('TRACE_OUTPUT', str(output.resolve()), flush=True)
    try:
        with BrowserSession(config) as session:
            def login_prompt(message):
                print('LOGIN_REQUIRED: complete login in project Chrome; then type login-ready', flush=True)
                while True:
                    session.context.pages[0].wait_for_timeout(250)
                    if select.select([sys.stdin], [], [], 0)[0] and sys.stdin.readline().strip() == 'login-ready':
                        return ''
            session.ensure_logged_in(prompt=login_prompt)
            trace.attach(session.context)
            # Mark every program-initiated hash fetch, including the upload success callback.
            original_verify = new_audit_module.verify_preview_content
            def traced_verify(*verify_args, **verify_kwargs):
                previous = trace.phase
                trace.mark('agent_content_verification')
                try:
                    return original_verify(*verify_args, **verify_kwargs)
                finally:
                    trace.mark(previous)
            new_audit_module.verify_preview_content = traced_verify
            runner = LifecycleRunner(session, WorkflowConfig(final_submit=False, page_timeout_ms=args.timeout*1000), trace, target_type, qualification)
            runner.company = company
            session.context.route('**/permit/web/permit/**', runner.guard)
            trace.emit('capture_config', timeout_ms=args.timeout*1000, final_submission_blocked=True,
                       routing_disables_http_cache=True, sample_files=[{'index': i+1, 'bytes': p.stat().st_size,
                       'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for i,p in enumerate(qualification.files)])
            trace.mark('navigate_to_company')
            try:
                runner.run_company(company)
            except Exception as first_error:
                # The real page may start a second URL-list query while trade config
                # is still initializing, cancelling our first read-only search.
                # Keep the same browser and retry only navigation, before any upload.
                trace.emit('initial_navigation_error', error_type=type(first_error).__name__)
                try:
                    if runner.page is not None:
                        raise first_error
                    overviews = [p for p in session.context.pages if not p.is_closed()
                                 and p.get_by_text('URL状态概览', exact=True).count()]
                    if len(overviews) != 1:
                        raise first_error
                    trace.mark('retry_read_only_url_navigation_after_initialization')
                    overviews[0].wait_for_timeout(5000)
                    detail = select_url_and_open_industry_qualification(
                        overviews[0], company.url, args.timeout*1000)
                    runner._run_industry_qualification(detail, company)
                except Exception as exc:
                    trace.emit('navigation_needs_inspection', error_type=type(exc).__name__,
                               sites=[{'module': Path(f.filename).name, 'line': f.lineno, 'function': f.name}
                                      for f in traceback.extract_tb(exc.__traceback__)])
                    print('NAVIGATION_PAUSED_BROWSER_RETAINED', flush=True)
            runner.command_loop()
    except Exception as exc:
        trace.emit('session_error', error_type=type(exc).__name__, error_ref=trace.redactor.alias(str(exc)),
                   sites=[{'module': Path(f.filename).name, 'line': f.lineno, 'function': f.name}
                          for f in traceback.extract_tb(exc.__traceback__)])
        print('SESSION_ERROR', type(exc).__name__, flush=True)
        return 1
    finally:
        trace.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
