from django.shortcuts import render
from django.views.generic import View
from forms import social_forms, pond_form
from models import (Notification, Follow, PictureSet, Picture, VoucheMilestone, SeenMilestone,
                    JournalPost, JournalComment, SeenProject, ProfilePictures, Pond, PondRequest,
                    PondMembership, PondSpecificProject)
from ..tasks.models import TikedgeUser, UserProject, Milestone, TagNames
from django.http import HttpResponseRedirect, HttpResponse
from django.utils.decorators import method_decorator
from django.core.urlresolvers import reverse
from django.core.exceptions import ObjectDoesNotExist
import modules
from ..tasks import modules as task_modules
from friendship.models import Friend, FriendshipRequest
from tasks_feed import NotificationFeed
from friendship.exceptions import AlreadyExistsError, AlreadyFriendsError
from django.core.exceptions import ValidationError
import global_variables
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
import json
from django.contrib import messages
from django.db.models import Q
from search_module import find_everything, find_project_and_milestone_by_tag
from braces.views import LoginRequiredMixin
from ..tasks.global_variables_tasks import TAG_NAMES_LISTS
from datetime import datetime


class CSRFExemptView(View):
    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super(CSRFExemptView, self).dispatch(*args, **kwargs)


class CSRFEnsureCookiesView(View):
    @method_decorator(ensure_csrf_cookie)
    def dispatch(self, *args, **kwargs):
        return super(CSRFEnsureCookiesView, self).dispatch(*args, **kwargs)


class JournalEntriesView(LoginRequiredMixin, View):

    def get(self, request):
        tkdge = TikedgeUser.objects.get(user=request.user)
        list_of_journal_feeds = modules.get_user_journal_feed(tkdge)
        return render(request, 'social/journal.html', {'list_of_journal_feeds':list_of_journal_feeds})

    def post(self, request):
        comment = request.POST.get("comment")
        response = {}
        if comment is not "":
            journal_id = request.POST.get("journal_id")
            journal = JournalPost.objects.get(id=int(journal_id))
            new_comment = JournalComment(journal_post=journal, comment=comment)
            new_comment.save()
            response["status"] = True
        else:
            response["status"] = True
        return HttpResponse(json.dumps(response), status=201)


class JournalCommentListView(LoginRequiredMixin, View):

    def get(self, request, slug):
        journal_post = JournalPost.objects.get(slug=slug)
        comments = journal_post.journalcomment_set.all().filter(is_deleted=False)
        print "comment ", comments
        return render(request, 'social/journal_thoughts.html', {'journal_comments':comments,
                                                                'journal_post':journal_post
                                                                })


class MilestoneView(LoginRequiredMixin, View):

    def get(self, request, slug):
        milestone = Milestone.objects.get(slug=slug)
        project = milestone.project
        project_name = project.name_of_project
        feed_id = milestone.id
        modules.increment_milestone_view(request.user, milestone)
        try:
            vouch_count = VoucheMilestone.objects.get(tasks=milestone).users.count()
        except ObjectDoesNotExist:
            vouch_count = 0
        try:
            seen_count = SeenMilestone.objects.get(tasks=milestone).users.count()
            print "seen count ", seen_count
            print "seen count ", seen_count
        except ObjectDoesNotExist:
            seen_count = 0
        project_completed = task_modules.time_has_past(project.length_of_project)
        user_first_name = milestone.user.user.first_name
        pic_list = milestone.pictureset_set.all().filter(~Q(after_picture=None))
        percentage = modules.get_milestone_percentage(milestone)
        start_time = task_modules.utc_to_local(milestone.reminder).strftime("%B %d %Y %I:%M %p")
        end_time = task_modules.utc_to_local(milestone.done_by).strftime("%B %d %Y %I:%M %p")
        return render(request, 'social/milestone_view.html', {
            'milestone':milestone, 'project_name':project_name,
            'feed_id':feed_id, 'vouch_count':vouch_count, 'seen_count':seen_count,
            'project_completed':project_completed, 'user_first_name': user_first_name,
            'project_slug':project.slug, 'pic_list': pic_list,
            'percentage':percentage,
            'end_time':end_time,
            'start_time':start_time
        })


class ProjectView(LoginRequiredMixin, View):

    def get(self, request, slug):
        project = UserProject.objects.get(slug=slug)
        project_name = project.name_of_project
        motivations = project.tags.all()
        user = project.user
        print "motivations ", motivations
        modules.increment_project_view(request.user, project)
        milestones = modules.milestone_tuple(project)
        try:
            seen_count = SeenProject.objects.get(tasks=project).users.count()
        except ObjectDoesNotExist:
            seen_count = 0
        try:
            follows = Follow.objects.get(tasks=project).users.count()
        except ObjectDoesNotExist:
            follows = 0
        if not project.is_public:
            pond_specific = PondSpecificProject.objects.get(project=project).pond.filter(is_deleted=False)
        else:
            pond_specific = None
        user_owns_proj = request.user == project.user.user
        return render(request, 'social/individual_project.html', {'project_name':project_name,
                                                                  'motivations':motivations,
                                                                   'milestones':milestones,
                                                                    'project_slug':slug,
                                                                    'seen_count':seen_count,
                                                                    'interest_count':follows,
                                                                    'project':project,
                                                                    'user':user,
                                                                    'pond_specific':pond_specific,
                                                                    'user_owns_proj':user_owns_proj
                                                                  })


class PictureUploadView(LoginRequiredMixin, View):

    def get(self, request):
        existing_milestones = task_modules.get_user_milestones(request.user)
        user_picture_form = social_forms.PictureUploadForm()
        return render(request, 'social/upload_picture.html', {'user_picture_form':user_picture_form,
                                                              'existing_milestones':existing_milestones})

    def post(self, request):
        user_picture_form = social_forms.PictureUploadForm(request.POST, request.FILES)

        if user_picture_form.is_valid() and 'picture' in request.POST:
            tkduser = TikedgeUser.objects.get(user=request.user)
            picture_file = request.FILES.get('picture', False)
            if not modules.file_is_picture(picture_file):
                messages.error(request, 'Hey visual must be either jpg, jpeg or png file!')
                existing_milestones = task_modules.get_user_milestones(request.user)
                return render(request, 'social/upload_picture.html', {'user_picture_form':user_picture_form,
                                                              'existing_milestones':existing_milestones})
            milestone_name = request.POST.get('milestone_name')
            milestone = Milestone.objects.get(id=milestone_name)
            if request.POST.get("type_of_picture") == global_variables.BEFORE_PICTURE:
                is_before = True
                # check that user is not creating concurrent before for current milestone
                try:
                    PictureSet.objects.get(milestone=milestone, after_picture=None, is_deleted=False)
                    messages.error(request, 'Sorry we first need an after picture for %s milestone' % milestone.name_of_milestone)
                    existing_milestones = task_modules.get_user_milestones(request.user)
                    return render(request, 'social/upload_picture.html', {'user_picture_form':user_picture_form,
                                                                          'existing_milestones':existing_milestones})
                except ObjectDoesNotExist:
                    pass
            else:
                is_before = False
            picture_file.file = modules.resize_image(picture_file)
            picture_mod = Picture(image_name=picture_file.name,
                                   milestone_pics=picture_file, tikedge_user=tkduser, is_before=is_before)
            picture_mod.save()
            if is_before:
                pic_set = PictureSet(before_picture=picture_mod, milestone=milestone, tikedge_user=tkduser)
                pic_set.save()
                day_entry = tkduser.journalpost_set.all().count()
                new_journal_entry = JournalPost(
                                                entry_blurb=modules.get_journal_message(global_variables.BEFORE_PICTURE,
                                                                                        milestone=milestone.blurb),
                                                                                        day_entry=day_entry + 1,
                                                                                        event_type=global_variables.BEFORE_PICTURE,
                                                                                        is_picture_set=True,
                                                                                        picture_set_entry=pic_set,
                                                                                        user=tkduser
                                                                                        )
                new_journal_entry.save()
                messages.success(request, 'Cool! The before visual entry added to %s milestone' % milestone.blurb)
            else:
                try:
                    pic_set = PictureSet.objects.get(milestone=milestone, after_picture=None, tikedge_user=tkduser, is_deleted=False)
                    pic_set.after_picture = picture_mod
                    pic_set.save()
                    day_entry = tkduser.journalpost_set.all().count()
                    new_journal_entry = JournalPost(
                                                entry_blurb=modules.get_journal_message(global_variables.AFTER_PICTURE,
                                                                                        milestone=milestone.blurb),
                                                day_entry=day_entry + 1,
                                                event_type=global_variables.AFTER_PICTURE,
                                                is_picture_set=True,
                                                 picture_set_entry=pic_set
                                                )
                    new_journal_entry.save()
                    messages.success(request, 'Great Job! The after visual entry added to %s milestone' % milestone.blurb)
                except ObjectDoesNotExist:
                    existing_milestones = task_modules.get_user_milestones(request.user)
                    messages.error(request, 'Hey we need a before visual entry before an after visual entry. This wow the crowd!')
                    return render(request, 'social/upload_picture.html', {'user_picture_form':user_picture_form,
                                                              'existing_milestones':existing_milestones})
            return HttpResponseRedirect(reverse('tasks:home'))
        existing_milestones = task_modules.get_user_milestones(request.user)
        messages.error(request, 'Oops, I think you forgot to upload a valid picture file')
        return render(request, 'social/upload_picture.html', {'user_picture_form':user_picture_form,
                                                              'existing_milestones':existing_milestones})


class TodoFeed(LoginRequiredMixin, View):

    def get(self, request):
        all_feeds = modules.get_users_feed(request.user)
        notification = Notification.objects.filter(user=request.user)
        notification = NotificationFeed(notifications=notification, user=request.user)
        unread_list = notification.get_unread_notification()
        tikedge_user = task_modules.get_tikedge_user(request.user)
        try:
            has_prof_pic = ProfilePictures.objects.get(tikedge_user=tikedge_user)
            user_pic_url = has_prof_pic.profile_pics.url
        except ObjectDoesNotExist:
            user_pic_url = None
        return render(request, 'social/news_feed.html', {'all_feeds':all_feeds,
                                                         'notifications':unread_list,
                                                         'user_pic_url': user_pic_url,
                                                         'user':request.user,
                                                         'slug':tikedge_user.slug
                                                         })


class SendFriendRequestView(View):

    def get(self, request):
        pass

    def post(self, request):
        user_id = request.POST.get("user_id")
        other_user = TikedgeUser.objects.get(id=int(user_id))
        print other_user.user.username, other_user.user.first_name, other_user.user.last_name
        message = "Hi %s %s username: %s would like to add you to his pond" % (request.user.first_name,
                  request.user.last_name, request.user.username)
        try:
            Friend.objects.add_friend(request.user, other_user.user, message=message)
            friend_request = FriendshipRequest.objects.get(pk=other_user.user.pk)
            notification = Notification(friend_request=friend_request, user=other_user.user,
                                        type_of_notification=global_variables.FRIEND_REQUEST)
            notification.save()
        except (AlreadyFriendsError, AlreadyExistsError, ValidationError):
            pass
        return HttpResponse('')


class AcceptFriendRequestView(View):

    def get(self, request):
        pass

    def post(self, request):
        request_id = request.POST.get("pk")
        print "Request ID %s", request_id
        try:
            friend_request = FriendshipRequest.objects.get(pk=int(request_id))
            friend_request.accept()
            # create notification
        except (AlreadyFriendsError, AlreadyExistsError, ValidationError):
            pass
        return HttpResponse('')


class RejectFriendRequestView(View):

    def get(self, request):
        pass

    def post(self, request):
        request_id = request.POST.get("pk")
        print "Request ID %s", request_id
        friend_request = FriendshipRequest.objects.get(pk=int(request_id))
        friend_request.reject()

        return HttpResponse('')


class FriendRequestView(View):

    def get(self, request):
        friend_request = Friend.objects.unread_requests(user=request.user)
        return render(request, 'social/friend_request.html', {'friend_request':friend_request})


class CreateVouch(View):

    def post(self, request, *args, **kwargs):
        response = {}
        milestone_id = request.POST.get("mil_id")
        milestone = Milestone.objects.get(id=int(milestone_id))
        user = TikedgeUser.objects.get(user=request.user)
        try:
            vouch_obj = VoucheMilestone.objects.get(tasks=milestone)
            if user in vouch_obj.users.all():
                vouch_obj.users.remove(user)
                vouch_obj.save()
                response["status"] = "unvouch"
                return HttpResponse(json.dumps(response), status=201)
        except ObjectDoesNotExist:
            vouch_obj = VoucheMilestone(tasks=milestone)
            vouch_obj.save()
        if user not in vouch_obj.users.all() and (user != milestone.user) and milestone.is_active:
            vouch_obj.users.add(user)
            vouch_obj.save()
            try:
                view = SeenMilestone.objects.get(tasks=milestone)
            except ObjectDoesNotExist:
                view = SeenMilestone(tasks=milestone)
                view.save()
            if user not in view.users.all():
                view.users.add(user)
                view.save()
                response["status"] = True
                vouch_notif = Notification(user=milestone.user.user,
                                        type_of_notification=global_variables.NEW_MILESTONE_VOUCH)
                vouch_notif.save()
            else:
                response["status"] = False
        else:
            response["status"] = False
        print "Tried to print vouch!!!!!!\n"
        return HttpResponse(json.dumps(response), status=201)


class CreateFollow(CSRFExemptView):

    def get(self, request, *args, **kwargs):
        return HttpResponse('')

    def post(self, request, *args, **kwargs):
        response = {}
        proj_id = request.POST.get("proj_id")
        project = UserProject.objects.get(id=int(proj_id))
        tikedge_user = TikedgeUser.objects.get(user=request.user)
        try:
            follow_obj = Follow.objects.get(tasks=project)
            if tikedge_user in follow_obj.users.all():
                follow_obj.users.remove(tikedge_user)
                follow_obj.save()
                response["status"] = "unfollow"
                response["count"] = follow_obj.users.all().count()
                return HttpResponse(json.dumps(response), status=201)
        except ObjectDoesNotExist:
            follow_obj = Follow(tasks=project)
            follow_obj.save()
        if tikedge_user != project.user:
            response["status"] = True
            follow_obj.users.add(tikedge_user)
            follow_obj.save()
            follow_notif = Notification(user=project.user.user,
                                        type_of_notification=global_variables.NEW_PROJECT_INTERESTED)
            follow_notif.save()
        else:
            response["status"] = False
        response["count"] = follow_obj.users.all().count()
        return HttpResponse(json.dumps(response), status=201)


class NotificationsViews(LoginRequiredMixin, View):

    def get(self, request):
        notif = modules.get_notifications_alert(request.user)
        return render(request, 'social/notification_view.html', {'notif':notif})


class NewPondertNotificationView(LoginRequiredMixin, View):
    """
        View for viewing all new people in your pond
    """
    def get(self, request):
        pond_reqs = modules.get_new_pond_member_notification(task_modules.get_tikedge_user(request.user))
        return render(request, 'social/new_ponders.html', {'pond_reqs':pond_reqs})

    def post(self, request):
        modules.mark_new_ponder_notification_as_read(request.user)
        data = {}
        data["status"] = True
        return HttpResponse(json.dumps(data))


class ProjectNotificationsView(LoginRequiredMixin, View):

    def get(self, request):
        tikegde_user = TikedgeUser.objects.get(user=request.user)
        all_project = tikegde_user.userproject_set.all()
        interest_feed = modules.get_interest_notification(all_project)
        return render(request, 'social/project_interest_view.html', {'interest_feed':interest_feed})

    def post(self, request):
        modules.mark_milestone_new_project_interested_as_read(request.user)
        data = {}
        data["status"] = True
        return HttpResponse(json.dumps(data))


class LetDownsNotificationsView(LoginRequiredMixin, View):
    def get(self, request):
        let_down_results = modules.let_downs(request.user)
        return render(request, 'social/let_down_view.html', {'let_down_results':let_down_results})

    def post(self, request):
        modules.mark_milestone_let_down_as_read(request.user)
        data = {}
        data["status"] = True
        return HttpResponse(json.dumps(data))


class VouchedNotificationsView(LoginRequiredMixin, View):

    def get(self, request):
        mil_down_results = modules.get_milestone_vouch_notifications(request.user)
        return render(request, 'social/milestone_vouches.html', {'mil_down_results':mil_down_results})

    def post(self, request):
        modules.mark_milestone_vouch_as_read(request.user)
        data = {}
        data["status"] = True
        return HttpResponse(json.dumps(data))


class NewPondRequestNotificationView(LoginRequiredMixin, View):
    """
    A view to show all pond request that a person can either accept or deny
    """
    def get(self, request):
        ponder_request = PondRequest.objects.filter(pond__pond_members__user=request.user).order_by('-date_requested')
        return render(request, 'social/pond_request_notification.html', {'pond_request':ponder_request})

    def post(self, request):
        modules.mark_pond_request_notification_as_read(request.user)
        modules.mark_milestone_pond_request_accepted_as_read(request.user)
        data = {}
        data["status"] = True
        return HttpResponse(json.dumps(data))


class FailedMilestonesNotificationView(LoginRequiredMixin, View):

    def get(self, request):
        notification = Notification.objects.filter(Q(user=request.user),
                                                   Q(type_of_notification=global_variables.USER_DELETED_MILESTONE)).order_by('-created')
        return render(request, 'social/failed_mil_notification.html', {'notifications':notification})

    def post(self, request):
        data = {}
        data["status"] = modules.mark_milestone_failed_as_read(request.user)
        return HttpResponse(json.dumps(data))


class FailedProjectNotificationView(LoginRequiredMixin, View):

    def get(self, request):
        notification = Notification.objects.filter(Q(user=request.user),
                                                   Q(type_of_notification=global_variables.USER_DELETED_PROJECT)).order_by('-created')
        return render(request, 'social/failed_proj_notification.html', {'notifications':notification})

    def post(self, request):
        data = {}
        data["status"] = modules.mark_project_failed_as_read(request.user)
        return HttpResponse(json.dumps(data))


class GetNotification(LoginRequiredMixin, View):

    def get(self, request):
        data = {}
        data["status"] = modules.notification_exist(request.user)
        return HttpResponse(json.dumps((data)))


class TagSearchView(LoginRequiredMixin, View):
    def get(self, request, word):
        results = find_project_and_milestone_by_tag(request.user, word)
        return render(request, 'social/search_results.html', {'results':results})


class SearchResultsView(LoginRequiredMixin, View):

    def get(self, request):
        query_word = request.GET["query_word"]
        results = find_everything(request.user, query_word)
        return render(request, 'social/search_results.html', {'results':results})


class PondView(LoginRequiredMixin, View):
    def get(self, request):
        ponds = modules.get_pond(request.user)
        return render(request, 'social/pond.html', {'ponders':ponds})


class AddToPond(LoginRequiredMixin, View):

    def post(self, request):
        data = {}
        pond_id = request.POST.get("pond_id")
        pond = Pond.objects.get(id=int(pond_id))
        user_id = request.POST.get("user_id")
        other_user = TikedgeUser.objects.get(id=int(user_id))
        try:
            pond_members = pond.pond_members.all()
            if other_user not in pond_members:
                for each_member in pond_members:
                    notification = Notification(user=each_member.user,
                                            type_of_notification=global_variables.NEW_PONDERS)
                    notification.save()
                pond.pond_members.add(other_user)
                pond.save()
                pond_membership = PondMembership(user=other_user, pond=pond)
                pond_membership.save()
                pond_request = PondRequest(user=other_user, pond=pond, date_response=datetime.now(),
                                           request_accepted=True,
                                           member_that_responded=task_modules.get_tikedge_user(request.user),
                                           request_responded_to=True)
                pond_request.save()
                notification = Notification(user=other_user.user,
                                            type_of_notification=global_variables.POND_REQUEST_ACCEPTED)
                notification.save()
                data['status'] = True
            else:
                print "others is here!!!!!!!!!"
        except (AttributeError, ValueError, TypeError):
            data['status'] = False
            data['error'] = "Something Went Wrong, Try Again!"
            pass
        return HttpResponse(json.dumps(data))


class PondRequestView(LoginRequiredMixin, View):
    """
        Send Pond Request to pond members
    """
    def post(self, request):
        pond_id = request.POST.get("pond_id")
        pond = Pond.objects.get(id=int(pond_id))
        data = modules.send_pond_request(pond, request.user)
        return HttpResponse(json.dumps(data))


class IndividualPondView(LoginRequiredMixin, View):

    def get(self, request, slug):
        the_pond = Pond.objects.get(slug=slug)
        pond_list_members = the_pond.pond_members.all()
        ponders = modules.get_pond_profile(pond_list_members, the_pond.pond_creator)
        tikedge_user = task_modules.get_tikedge_user(request.user)
        pond_member = pond_list_members.filter(user=tikedge_user.user)
        pond_status = task_modules.get_pond_status(pond_list_members)
        '''
        try:
            ponders.index(tikedge_user)
            pond_member = True
        except ValueError:
            pond_member = False
        '''
        return render(request, 'social/individual_pond.html',
                      {
                          'ponders':ponders,
                          'pond':the_pond,
                           'pond_member':pond_member,
                            'pond_stage':pond_status
                      })

    def post(self, request):
        return


class NewPondEntryView(LoginRequiredMixin, View):

    def get(self, request):
        form = pond_form.PondEntryForm()
        return render(request, 'social/new_pond_entry.html', {'form':form, 'tag_names':TAG_NAMES_LISTS})

    def post(self, request):
        form = pond_form.PondEntryForm(request.POST)
        if form.is_valid():
            pond_name = form.cleaned_data.get('name_of_pond')
            purpose = form.cleaned_data.get('purpose')
            tags = request.POST.getlist('tags')
            pond = Pond(name_of_pond=pond_name, purpose=purpose,
                        pond_creator=task_modules.get_tikedge_user(request.user))
            pond.save()
            for item in tags:
                print tags, " tags why"
                try:
                    item_obj = TagNames.objects.get(name_of_tag=item)
                except ObjectDoesNotExist:
                    item_obj = TagNames(name_of_tag=item)
                    item_obj.save()
                pond.tags.add(item_obj)
            pond.pond_members.add(task_modules.get_tikedge_user(request.user))
            pond.save()
            pond_membership = PondMembership(user=task_modules.get_tikedge_user(request.user),
                                             pond=pond)
            pond_membership.save()
            messages.success(request, "%s was created!" % pond_name)
            return HttpResponseRedirect(reverse('tasks:home'))
        task_modules.display_error(form, request)
        return render(request, 'social/new_pond_entry.html', {'form':form, 'tag_names':TAG_NAMES_LISTS})


class AcceptPondRequest(LoginRequiredMixin, View):

    def post(self, request):
        data = {}
        pond_request_id = request.POST.get("pond_request_id")
        pond_request = PondRequest.objects.get(id=int(pond_request_id))
        if pond_request.request_responded_to:
            data["status"] = "already exist"
            return HttpResponse(json.dumps(data))
        else:
            try:
                pond_request.date_response = datetime.now()
                pond_request.request_accepted = True
                pond_request.request_responded_to = True
                pond_request.member_that_responded = task_modules.get_tikedge_user(request.user)
                pond_request.save()
                data["status"] = "accepted"
                new_notif = Notification(user=pond_request.user.user, type_of_notification=global_variables.POND_REQUEST_ACCEPTED)
                new_notif.save()
                for each_member in pond_request.pond.pond_members.all():
                    new_notif = Notification(user=each_member.user, type_of_notification=global_variables.NEW_PONDERS)
                    new_notif.save()
                pond_request.pond.pond_members.add(pond_request.user)
                pond_request.pond.save()
                pond_membership = PondMembership(user=pond_request.user, pond=pond_request.pond)
                pond_membership.save()
                return  HttpResponse(json.dumps(data))
            except (AttributeError, ValueError, TypeError):
                data["status"] = "error"
                return HttpResponse(json.dumps(data))


class DenyPondRequest(LoginRequiredMixin, View):

    def post(self, request):
        data = {}
        pond_request_id = request.POST.get("pond_request_id")
        pond_request = PondRequest.objects.get(id=int(pond_request_id))
        if pond_request.request_responded_to:
            data["status"] = "already exist"
            return HttpResponse(json.dumps(data))
        else:
            try:
                pond_request.date_response = datetime.now()
                pond_request.request_accepted = False
                pond_request.request_denied = True
                pond_request.request_responded_to = True
                pond_request.member_that_responded = task_modules.get_tikedge_user(request.user)
                pond_request.save()
                data["status"] = "accepted"
                return  HttpResponse(json.dumps(data))
            except (AttributeError, ValueError, TypeError):
                data["status"] = "error"
                return HttpResponse(json.dumps(data))


class  EditPictureSetView(LoginRequiredMixin, View):
    """
    Remove Complete Pictures. Edit Pictures Without After Shot (i.e Delete Them or Change Them).
    """

    def get(self, request):
        tikedge_user = TikedgeUser.objects.get(user=request.user)
        form = social_forms.EditPictureSetForm()
        user_picture_set = PictureSet.objects.filter(tikedge_user=tikedge_user, is_deleted=False)
        try:
            has_prof_pic = ProfilePictures.objects.get(tikedge_user=tikedge_user)
        except ObjectDoesNotExist:
            has_prof_pic = None
        return render(request, 'tasks/settings/edit_picture_set.html',
                      {'user_picture_set':user_picture_set,
                       'form':form,
                       'has_prof_pic':has_prof_pic,
                       'tikedge_user':tikedge_user
                       })

    def post(self, request):
        form = social_forms.EditPictureSetForm(request.POST, request.FILES)
        tikedge_user = TikedgeUser.objects.get(user=request.user)
        if 'change_picture_after' in request.POST:
            pic_set_id = request.POST.get("change_picture_after")
            picture = Picture.objects.get(id=int(pic_set_id))
            if form.is_valid():
                pic_file = request.FILES.get('picture', False)
                if modules.file_is_picture(pic_file):
                    pic_file.file = modules.resize_image(pic_file)
                    picture.milestone_pics = pic_file
                    picture.image_name = pic_file.name
                    picture.last_edited = datetime.now()
                    picture.save()
                    messages.success(request, "Picture Information Updated!")
                else:
                    messages.error(request, 'Hey visual must be either jpg, jpeg or png file!')
            else:
                messages.success(request, "Invalid Picture Upload")
        if 'change_picture_before' in request.POST:
            pic_set_id = request.POST.get("change_picture_before")
            picture = Picture.objects.get(id=int(pic_set_id))
            if form.is_valid():
                pic_file = request.FILES.get('picture', False)
                if modules.file_is_picture(pic_file):
                    pic_file.file = modules.resize_image(pic_file)
                    picture.milestone_pics = pic_file
                    picture.image_name = pic_file.name
                    picture.last_edited = datetime.now()
                    picture.save()
                    messages.success(request, "Picture Information Updated!")
                else:
                    messages.error(request, 'Hey visual must be either jpg, jpeg or png file!')
            else:
                messages.success(request, "Invalid Picture Upload")
        if 'delete_picture_after' in request.POST:
            pic_id = request.POST.get("delete_picture_after")
            picture = Picture.objects.get(id=int(pic_id))
            picture.is_deleted = True
            picture.last_edited = datetime.now()
            picture.save()
            picture_set = PictureSet.objects.get(after_picture=picture)
            picture_set.after_picture = None
            picture_set.save()
            messages.success(request, "Picture Deleted")
        if 'delete_picture_before' in request.POST:
            pic_id = request.POST.get("delete_picture_before")
            picture = Picture.objects.get(id=int(pic_id))
            picture.is_deleted = True
            picture.last_edited = datetime.now()
            picture.save()
            picture_set = PictureSet.objects.get(before_picture=picture)
            picture_set.before_picture = None
            picture_set.is_deleted = True
            picture_set.save()
            messages.success(request, "Picture Deleted")
        try:
            has_prof_pic = ProfilePictures.objects.get(tikedge_user=tikedge_user)
        except ObjectDoesNotExist:
            has_prof_pic = None
        user_picture_set = PictureSet.objects.filter(tikedge_user=tikedge_user, is_deleted=False)
        return render(request, 'tasks/settings/edit_picture_set.html',
                      {'user_picture_set':user_picture_set,
                       'form':form,
                       'has_prof_pic':has_prof_pic,
                       'tikedge_user':tikedge_user
                       })


class DeletePictureSet(LoginRequiredMixin, View):

    def post(self, request):
        try:
            pic_set_id = request.POST.get("pic_set_id")
            pic_set = PictureSet.objects.get(id=int(pic_set_id))
            pic_set.is_deleted = True
            pic_set.save()
            response = {'status':True}
        except ObjectDoesNotExist:
            response = {'status':False}
        return HttpResponse(json.dumps(response))


class EditPondView(LoginRequiredMixin, View):

    def get(self, request):
        tikedge_user = TikedgeUser.objects.get(user=request.user)
        ponds = Pond.objects.filter(pond_members__user=tikedge_user.user, is_deleted=False)
        try:
            has_prof_pic = ProfilePictures.objects.get(tikedge_user=tikedge_user)
        except ObjectDoesNotExist:
            has_prof_pic = None
        return render(request, 'tasks/settings/pond_edit.html',
                      {
                       'ponds':ponds,
                       'tikedge_user':tikedge_user,
                        'has_prof_pic':has_prof_pic
                       })

    def post(self, request):
        response = {"status":False}
        if 'pond_id' in request.POST:
            pond_id = request.POST.get("pond_id")
            pond = Pond.objects.get(id=int(pond_id))
            pond.is_deleted = True
            pond.save()
            response = {"status":True}
        return HttpResponse(json.dumps(response))


class EditIndividualPondView(LoginRequiredMixin, View):

    def get(self, request, slug):
        pond = Pond.objects.get(slug=slug)
        form = pond_form.EditPondEntryForm(initial={
            'name_of_pond':pond.name_of_pond,
            'purpose':pond.purpose,
        })
        tikedge_user = TikedgeUser.objects.get(user=request.user)
        select_tags = modules.get_tag_list(pond.tags.all())
        pond_members = pond.pond_members.all()
        return render(request, 'tasks/settings/individual_pond_edit.html',
                                {
                                 'tikedge_user':tikedge_user,
                                 'form':form,
                                 'tag_names':TAG_NAMES_LISTS,
                                 'select_tags':select_tags,
                                 'pond':pond,
                                 'pond_members':pond_members
                                 })

    def post(self, request, slug):
        form = pond_form.PondEntryForm(request.POST)
        pond = Pond.objects.get(slug=slug)
        pond_members = pond.pond_members.all()
        tikedge_user = TikedgeUser.objects.get(user=request.user)
        if form.is_valid():
            pond_name = form.cleaned_data.get('name_of_pond')
            purpose = form.cleaned_data.get('purpose')
            tags = request.POST.getlist('tags')
            ponders = request.POST.getlist('ponders')
            pond.name_of_pond = pond_name
            pond.purpose = purpose
            pond.save()
            for item in pond.tags.all():
                pond.tags.remove(item)
            pond.save()
            for item in tags:
                try:
                    item_obj = TagNames.objects.get(name_of_tag=item)
                except ObjectDoesNotExist:
                    item_obj = TagNames(name_of_tag=item)
                    item_obj.save()
                pond.tags.add(item_obj)
            for pd in ponders:
                tik = TikedgeUser.objects.get(id=pd)
                pond.pond_members.remove(tik)
            pond.save()
            messages.success(request, "%s was updated!" % pond_name)
            return HttpResponseRedirect(reverse('social:edit_pond'))
        task_modules.display_error(form, request)
        select_tags = modules.get_tag_list(pond.tags.all())
        print "select tags", select_tags
        return render(request, 'tasks/settings/individual_pond_edit.html',
                      {
                          'tikedge_user':tikedge_user,
                          'form':form,
                          'tag_names':TAG_NAMES_LISTS,
                          'select_tags':select_tags,
                          'pond':pond,
                          'pond_members':pond_members
                       })
