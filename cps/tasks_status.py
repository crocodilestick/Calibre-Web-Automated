# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from markupsafe import escape

from flask import Blueprint, jsonify
from .cw_login import current_user
from flask_babel import gettext as _
from flask_babel import format_datetime
from babel.units import format_unit

from . import logger
from .render_template import render_title_template
from .services.worker import WorkerThread, STAT_WAITING, STAT_FAIL, STAT_STARTED, STAT_FINISH_SUCCESS, STAT_ENDED, \
    STAT_CANCELLED
from .usermanagement import user_login_required

tasks = Blueprint('tasks', __name__)

log = logger.create()


@tasks.route("/ajax/emailstat")
@user_login_required
def get_email_status_json():
    tasks = WorkerThread.get_instance().tasks
    return jsonify(render_task_status(tasks))


@tasks.route("/tasks")
@user_login_required
def get_tasks_status():
    # if current user admin, show all email, otherwise only own emails
    return render_title_template('tasks.html', title=_("Tasks"), page="tasks")


# helper function to apply localize status information in tasklist entries
def render_task_status(tasklist):
    rendered_tasklist = list()
    for __, user, __, task, __ in tasklist:
        if user == current_user.name or current_user.role_admin():
            ret = {}
            if task.start_time:
                # Use ISO-like date format for consistency across locales
                ret['starttime'] = format_datetime(task.start_time, format="yyyy-MM-dd HH:mm")
                ret['runtime'] = format_runtime(task.runtime)

            # localize the task status
            if isinstance(task.stat, int):
                if task.stat == STAT_WAITING:
                    ret['status'] = _('Waiting')
                elif task.stat == STAT_FAIL:
                    ret['status'] = _('Failed')
                elif task.stat == STAT_STARTED:
                    ret['status'] = _('Started')
                elif task.stat == STAT_FINISH_SUCCESS:
                    ret['status'] = _('Finished')
                elif task.stat == STAT_ENDED:
                    ret['status'] = _('Ended')
                elif task.stat == STAT_CANCELLED:
                    ret['status'] = _('Cancelled')
                else:
                    ret['status'] = _('Unknown Status')

            ret['taskMessage'] = "{}: {}".format(task.name, task.message) if task.message else task.name
            ret['progress'] = "{} %".format(int(task.progress * 100))
            ret['user'] = escape(user)  # prevent xss

            # Hidden fields
            ret['task_id'] = task.id
            ret['stat'] = task.stat
            ret['is_cancellable'] = task.is_cancellable
            ret['error'] = task.error

            rendered_tasklist.append(ret)

    return rendered_tasklist


# helper function for displaying the runtime of tasks
def format_runtime(runtime):
    ret_val = ""
    if runtime.days:
        ret_val = format_unit(runtime.days, 'duration-day', length="long") + ', '
    minutes, seconds = divmod(runtime.seconds, 60)
    hours, minutes = divmod(minutes, 60)
    # ToDo: locale.number_symbols._data['timeSeparator'] -> localize time separator ?
    if hours:
        ret_val += '{:d}:{:02d}:{:02d}s'.format(hours, minutes, seconds)
    elif minutes:
        ret_val += '{:2d}:{:02d}s'.format(minutes, seconds)
    else:
        ret_val += '{:2d}s'.format(seconds)
    return ret_val
