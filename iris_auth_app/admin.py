from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    Assessment,
    AttendanceRecord,
    FeeRecord,
    InternalMark,
    IrisTemplate,
    IrisUser,
    TimetableEntry,
)


class IrisTemplateInline(admin.StackedInline):
    model = IrisTemplate
    can_delete = True
    extra = 0
    readonly_fields = (
        'created_at',
        'updated_at',
        'code_shape',
        'code_dtype',
        'mask_shape',
        'mask_dtype',
        'encoding_version',
    )
    fields = (
        'enrollment_status',
        'encoding_version',
        ('code_shape', 'code_dtype'),
        ('mask_shape', 'mask_dtype'),
        ('created_at', 'updated_at'),
    )


@admin.register(IrisUser)
class IrisUserAdmin(UserAdmin):
    list_display = (
        'username',
        'display_name',
        'student_id',
        'is_staff',
        'is_active',
        'has_iris_template',
        'created_at',
    )
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'created_at')
    search_fields = ('username', 'display_name', 'student_id', 'email')
    ordering = ('username',)
    inlines = [IrisTemplateInline]

    fieldsets = UserAdmin.fieldsets + (
        ('Iris Profile', {'fields': ('display_name', 'student_id')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            'Iris Profile',
            {
                'classes': ('wide',),
                'fields': ('display_name', 'student_id'),
            },
        ),
    )

    @admin.display(boolean=True, description='Iris Enrolled')
    def has_iris_template(self, obj):
        return hasattr(obj, 'iris_template') and obj.iris_template is not None


@admin.register(IrisTemplate)
class IrisTemplateAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'enrollment_status',
        'encoding_version',
        'code_shape',
        'created_at',
        'updated_at',
    )
    list_filter = ('enrollment_status', 'encoding_version', 'created_at')
    search_fields = ('user__username', 'user__student_id', 'user__display_name')
    readonly_fields = (
        'user',
        'created_at',
        'updated_at',
        'code_shape',
        'code_dtype',
        'mask_shape',
        'mask_dtype',
        'encoding_version',
    )


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ('student', 'subject', 'attended_classes', 'total_classes', 'updated_at')
    list_filter = ('subject',)
    search_fields = ('student__username', 'student__student_id', 'subject')


@admin.register(FeeRecord)
class FeeRecordAdmin(admin.ModelAdmin):
    list_display = ('student', 'fee_type', 'amount_due', 'amount_paid', 'outstanding_balance', 'due_date')
    list_filter = ('fee_type',)
    search_fields = ('student__username', 'student__student_id', 'fee_type')


@admin.register(TimetableEntry)
class TimetableEntryAdmin(admin.ModelAdmin):
    list_display = ('student', 'day', 'start_time', 'end_time', 'subject', 'room', 'faculty')
    list_filter = ('day', 'subject')
    search_fields = ('student__username', 'student__student_id', 'subject', 'faculty')


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = ('student', 'title', 'subject', 'assessment_type', 'due_date', 'submitted')
    list_filter = ('assessment_type', 'subject', 'submitted')
    search_fields = ('student__username', 'student__student_id', 'title', 'subject')


@admin.register(InternalMark)
class InternalMarkAdmin(admin.ModelAdmin):
    list_display = ('student', 'subject', 'exam_type', 'obtained_marks', 'max_marks', 'percentage')
    list_filter = ('subject', 'exam_type')
    search_fields = ('student__username', 'student__student_id', 'subject')
