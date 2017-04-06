# Andriy Zatserklyaniy <zatserkl@gmail.com> Apr 3, 2017

from datetime import datetime, timedelta
from collections import deque, defaultdict

class NoSignUTC(Exception):
    pass

class FormatError(Exception):
    pass

class LogAnalysis:
    """
    Method.
    For each failed ip we use a container buf_fail for 3 last failed login attempts.
    After third failed login we add an +5 minutes time moment to empty container time_unblock.
    Successful login clears the container buf_fail: removes the entry for this ip.
    """

    def __init__(self, ofname_hosts_txt, ofname_hours_txt, ofname_resources_txt, ofname_blocked_txt):

        self.ofname_hosts_txt = ofname_hosts_txt
        self.ofname_hours_txt = ofname_hours_txt
        self.ofname_resources_txt = ofname_resources_txt
        self.ofname_blocked_txt = ofname_blocked_txt
        
        self.debug = False
        # self.debug = True

        self.html_code_Unauthorized = 401       # HTML code for failed login attempt
        self.html_code_OK = 200                 # HTML code for successful login attempt

        # parameters
        self.time_range_fail = 20               # time in seconds range to count failed login attempts
        self.nfail = 3                          # the number of failed logins to be blocked
        self.nminutes = 5                       # block ip for nminutes

        # properties of the current event (line)
        self.ip = ''
        self.date_time_offset = ''              # string representation of time
        self.time = timedelta(0)                # datetime representation of time
        self.request = ''
        self.resourse = ''
        self.html_code = 0
        self.len_replay = 0
        self.time_local = timedelta(0)
        self.time_utc = timedelta(0)
        self.utc_offset = timedelta(0)          # UTC offset: info about time zone
        self.good_event = False

        self.extract_fields_init = True         # init constants of the method extract_fields

        # constant values to speedup initialization
        self.datetime_zero = datetime(1990, 1, 1, 0, 0, 0)      # level zero
        self.time_block = timedelta(0, self.nminutes*60)        # timedelta for block in seconds

        #
        # deque of constant length nfail for the last nfail elements
        #
        self.buf_fail = defaultdict(lambda: deque(self.nfail*[self.datetime_zero], maxlen=self.nfail))

        #
        # container for the value of time to unblock access for the failed ip
        #
        self.time_unblock = defaultdict(list)

        #
        # Analytics
        #

        # self.top_hours = []                     # pairs (time, nvisits)
        # self.bins = [0 for _ in range(2*3600)]  # bins (seconds) for 2 hours
        # self.time0 = self.datetime_zero         # time for the first bin
        # self.time0_offset = self.datetime_zero  # constant value of the UTC offset (for convenience)
        self.nhours = 10                          # top 10 hours
        self.top_hours = self.nhours*[('a', 0)]   # pairs (time, nvisits)
        self.busy_hours_init = True               # flag to init method busy_hours

        self.seconds = 10000000*[0]
        self.tsec = []  # 10000000*[0]
        self.tvis = []  # 10000000*[0]
        self.tcur = -1;
        self.nseconds = 0
        self.seconds_tot = 0

        self.time0_loc = self.datetime_zero

        self.hosts = defaultdict(int)           # host frequency

        self.resources = defaultdict(int)       # resources bandwidth

        self.ofile_blocked_txt = open(ofname_blocked_txt, 'w')

    def process_file(self, ifname_log_txt):
        """
        Loops over the data file lines
        """

        line_start, nlines_max = 0, 0
        # line_start, nlines_max = 0, 20
        # line_start, nlines_max = 0, 1000
        # line_start, nlines_max = 0, 4000000
        # line_start, nlines_max = 1600000, 0
        # line_start, nlines_max = 0, 1         # the first line
        # line_start, nlines_max = 117, 10      # replay of zero bytes: hyphen
        # line_start, nlines_max = 0, 100        # the first line
        # line_start, nlines_max = 0, 10000        # the first line

        nlines = 0
        with open(ifname_log_txt, 'r') as file:
            for iline, self.line in enumerate(file):

                if iline % 1000000 == 0: print 'processing line', iline

                if iline < line_start:
                    continue

                nlines += 1
                if nlines_max > 0 and nlines > nlines_max:
                    break

                if nlines > 20:
                    self.debug = False          # forse debug off for large output

                try:
                    self.extract_fields()
                    self.parse_time()

                except FormatError as e:
                    print 'Format error in line', iline, e.args[0]
                    continue
                except ValueError:
                    print 'Format error (ValueError) in line', iline
                    continue
                except NoSignUTC as e:
                    print '***Warning parse_time: Caught NoSignUTC exception e.args[0]:', e.args[0]
                    continue

                if self.debug:
                    print iline, '\t', \
                        self.ip, self.date_time_offset, self.resource, self.html_code, self.len_replay, \
                        self.time_local, self.time_utc

                #
                # At this point we have all the information successfully extracted
                #

                self.runtime_block()

                #
                # run analytics
                #

                self.hosts[self.ip] += 1

                if len(self.resource) > 1:      # ignore empty string and just slash symbol '/'
                    self.resources[self.resource] += self.len_replay

                self.busy_hours()               # collect busy hours info from each event

        #
        # Final processing after loop over events
        #

        #
        # Summarize busy hours
        #

        self.busy_hours_hist()          # process collected histogram

        #
        # The most frequent hosts
        #

        print '\nhosts:'
        nprint = 0
        with open(ofname_hosts_txt, "w") as ofile_hosts:
            for host in sorted(self.hosts, key=self.hosts.get, reverse=True):
                line = "%s,%d\n" % (host, self.hosts[host])
                print nprint, line,
                ofile_hosts.write(line)
                nprint += 1
                if nprint >= 10:
                    break

        #
        # The most bandwidth-hungry resources
        #

        print '\nresources:'
        nprint = 0
        with open(ofname_resources_txt, "w") as ofile_resources:
            for resource in sorted(self.resources, key=self.resources.get, reverse=True):
                # line = "%s, %d\n" % (resource, self.resources[resource])
                line = "%s\n" % (resource)
                print nprint, line,
                ofile_resources.write(line)
                nprint += 1
                if nprint >= 10:
                    break

    def extract_fields(self):
        """
        Extracts data fields from the original line:
        ip
        time string
        request string
        HTML code
        request length
        """

        # parse constants
        if self.extract_fields_init:
            self.ip_separator = ' - - '
            self.len_separator = len(self.ip_separator)
            self.len_date = len('01/Jul/1995:00:00:01 -0400')
            self.extract_fields_init = False

        self.good_event = False
        ip_end = self.line.find(self.ip_separator)    # one position after the ip
        if ip_end < 0:
            raise FormatError("Error in ip")
        self.ip = self.line[0: ip_end]

        self.date_time_offset = self.line[ip_end+self.len_separator+1: ip_end+self.len_separator+1+self.len_date]

        request_start = self.line.find('"')
        request_end = self.line.rfind('"')

        if request_start < 0:
            raise FormatError("Error in request")
        if request_end == request_start:
            raise FormatError("Error in request")

        self.request = self.line[request_start+1: request_end]

        resource_start = self.request.find(' ')              # one position before the request
        if resource_start < 0:
            raise FormatError("Error in resource")
        resource_end = self.request.rfind(' ')
        if resource_end < 0:
            raise FormatError("Error in resource")
        self.resource = self.request[resource_start+1: resource_end].strip(' \t\n\r')   # strip spaces

        code_bytes = self.line[request_end+1:].split()
        self.html_code = int(code_bytes[0])
        self.len_replay = 0
        if code_bytes[1] != '-': self.len_replay = int(code_bytes[1])

        self.good_event = True
        return

    def parse_time(self):
        """
        Processes time information:
        1) converts time string to datetime
        2) gets UTC time by adding the UTC offset
        """
        self.good_event = False

        tlist = self.date_time_offset.split()
        self.time_local = datetime.strptime(tlist[0], "%d/%b/%Y:%H:%M:%S")
        offset = tlist[1]

        self.time_utc = self.time_local
        self.utc_offset = timedelta(hours=int(offset[1:3]), minutes=int(offset[3:5]))

        if offset[0] == '+':
            self.time_utc = self.time_local + self.utc_offset
        elif offset[0] == '-':
            self.time_utc = self.time_local - self.utc_offset
        else:
            raise NoSignUTC('there is no sign in UTC offset')

        self.good_event = True

    def runtime_block(self):
        """
        Processes two HTML code: for failed login (401) and for successful login (200) attempts
        """
        if self.ip in self.time_unblock:
            #
            # this ip was blocked some time ago
            #
            if self.time_utc < self.time_unblock[self.ip][0]:
                #
                # attempt of access during the blocked time
                #
                self.ofile_blocked_txt.write(self.line) # make an entry into blocked.txt
                return                                  # done with this event
            else:
                #
                # block time was over, clear the time_unblock: remove the entry for the ip
                #
                self.time_unblock.pop(self.ip, None)
                #
                # analyse the request with the code below this if-section
                #

        # NB: the ip is not blocked at this point

        if self.html_code == self.html_code_Unauthorized:
            # add to the deque under index 0
            self.buf_fail[self.ip].appendleft(self.time_utc)
            # check the time difference with the first item
            delta = self.buf_fail[self.ip][0] - self.buf_fail[self.ip][-1]

            if delta.total_seconds() < self.time_range_fail:
                #
                # We detected 3 failed login attempts during 5 minutes interval
                #
                #-- print 'self.buf_fail[', self.ip, '][0]:', delta.total_seconds(), '   -->', self.date_time_offset

                # create a +5 minutes time_unblock for this ip
                time = self.time_utc + self.time_block
                self.time_unblock[self.ip].append(time)
            else:
                # the time difference more than 20 s
                pass

        elif self.html_code == self.html_code_OK:
            # clear the history: remove the entry for the ip from the dictionary
            self.buf_fail.pop(self.ip, None)
        return

    def busy_hours(self):
        """
        Fills the histogram and sorted array for (time, nvisits) pairs
        """
        if self.busy_hours_init:
            # histograms
            #-- self.nhours = 10                                            # top 10 hours
            #-- self.top_hours = self.nhours*[0]                            # pairs (time, nvisits)
            #-- self.top_hours = self.nhours*[('a', 0)]                            # pairs (time, nvisits)
            #-- print 'self.top_hours:', self.top_hours

            # self.hour = 3600
            # self.nbins = 2*self.hour
            # #self.bins = [0 for _ in range(nbins)]                      # bins (seconds) for 2 hours
            # self.bins = deque(self.nbins*[0], maxlen=self.nbins)        # bins (seconds) for 2 hours
            # self.first = 0                                              # the first bin

            # use the first good event to init
            self.time0 = self.time_utc                  # time for the first bin
            self.time0_offset = self.utc_offset         # constant value of the UTC offset (for convenience)
            self.time0_loc = self.time_local
            self.busy_hours_init = False                # turn off initialization

        # # find the histogram bin for the current event
        # delta = self.time_utc - self.time0
        # bin = int(delta.total_seconds()) - self.first
        # if bin < self.hour:
        #     for ibin in range(bin):
        #         self.bins[(self.first + ibin) % self.nbins] += 1
        # else:
        #     #print '\nShift buffer\n'

        #     # the first bin went out of scope. Process it.
        #     nprocess = bin - self.hour
        #     for ibin in range(nprocess):
        #         # create pair
        #         time_dt = self.time0 + timedelta(0, ibin)       # add ibin seconds
        #         time_dt += self.time0_offset                    # convert to local time
        #         time_str = time_dt.strftime("%d/%b/%Y:%H:%M:%S")
        #         time_str += ' -0400'                            # TODO: use convert
        #         p = (time_str, self.bins[(self.first + ibin) % self.nbins])

        #         n = 0
        #         while p[1] < self.top_hours[n][1]:
        #             n += 1
        #             if n >= len(self.top_hours):
        #                 break

        #         self.top_hours.insert(n, p)
        #         self.top_hours.pop()            # remove last item

        #         self.first += 1
        #         self.time0 += timedelta(0, 1)   # add 1 second

        #     # print self.top_hours
        #     # for p in self.top_hours:
        #     #    print 'p:', p[0], p[1]

        #################################
        #                               #
        #  Currently working algorithm  #
        #                               #
        #################################

        delta = self.time_utc - self.time0
        ikey = int(delta.total_seconds())
        if self.tcur == ikey:
            # self.tvis[self.tcur] += 1
            self.tvis[len(self.tvis) - 1] += 1
        else:
            self.tcur = ikey
            self.tsec.append(ikey)
            self.tvis.append(1)

        if ikey >= 0 and ikey < 10000000:
            if ikey > self.nseconds:
                self.nseconds = ikey
            self.seconds[ikey] += 1
            self.seconds_tot = ikey
            # print 'ikey =', ikey
        else:
            print 'ikey =', ikey, 'out of range'

    def busy_hours_hist(self):
        """
        Processes busy hours histogram using moving average algorithm
        """
        time_dt = self.time0_loc
        time_str = time_dt.strftime("%d/%b/%Y:%H:%M:%S")
        time_str += ' -0400'
        visits = sum(self.seconds[:3600])
        p = (time_str, visits)
        self.top_hours[0] = p

        # pair of two indices
        first = 0               # the first point of the current hour
        last = self.tsec[-1]    # the first point beyond the current hour

        run_sum = 0
        nhours = 0
        for last in range(len(self.tsec)):
            if self.tsec[last] > 3600:
                break
            run_sum += self.tvis[last]

        time_dt = self.time0_loc + timedelta(0, 0)
        time_str = time_dt.strftime("%d/%b/%Y:%H:%M:%S")
        time_str += ' -0400'
        p = (time_str, run_sum)
        # self.top_hours.insert(0, p)
        # self.top_hours.pop()

        run_sum_max = run_sum
        time_str_max = time_str

        # print 'before main loop: last =', last, 'self.tsec[last] =', self.tsec[last]

        for first in range(1, len(self.tsec)):
            run_sum -= self.tvis[first-1]   # remove the first point from the running sum
            while self.tsec[last] - self.tsec[first] < 3600:
                last += 1
                if last >= len(self.tsec):
                    last = len(self.tsec) - 1
                    break

                run_sum += self.tvis[last]  # add

            time_dt = self.time0_loc + timedelta(0, self.tsec[first])
            time_str = time_dt.strftime("%d/%b/%Y:%H:%M:%S")
            time_str += ' -0400'
            p = (time_str, run_sum)

            if run_sum > run_sum_max:
                run_sum_max = run_sum
                time_str_max = time_str

            # print run_sum
            # if first < 10000000:
            #     print 'first =', first, 'last =', last, 'self.tsec[firt] =', self.tsec[first], 'self.tsec[last] =', self.tsec[last], 'dt =', self.tsec[last] - self.tsec[first], 'run_sum =', run_sum

            n = 0
            while p[1] < self.top_hours[n][1]:
                n += 1
                if n >= len(self.top_hours):
                    break

            self.top_hours.insert(n, p)
            self.top_hours.pop()

        # print '\nrun_sum_max =', run_sum_max, 'time_str_max =', time_str_max

        print '\nBusy hours'
        with open(ofname_hours_txt, "w") as ofile_hours:
            for p in self.top_hours:
                if p[0] == 'a' and p[1] == 0:       # this is an initial content
                    break
                line = "%s,%d\n" % (p[0], p[1])
                print line,
                ofile_hours.write(line)

import sys

if __name__ == '__main__':

    ifname_log_txt = ''
    ofname_hosts_txt = ''
    ofname_hours_txt = ''
    ofname_resources_txt = ''
    ofname_blocked_txt = ''

    # ifname_log_txt = './log_input/log.txt'
    # ofname_hosts_txt = './log_output/hosts.txt'
    # ofname_hours_txt = './log_output/hours.txt'
    # ofname_resources_txt = './log_output/resources.txt'
    # ofname_blocked_txt = './log_output/blocked.txt'

    # for i, arg in enumerate(sys.argv):
    #     print "sys.argv[{0}] = {1}".format(i, arg)

    if len(sys.argv) == 6:
        ifname_log_txt = sys.argv[1]
        ofname_hosts_txt = sys.argv[2]
        ofname_hours_txt = sys.argv[3]
        ofname_resources_txt = sys.argv[4]
        ofname_blocked_txt = sys.argv[5]

    print
    print 'ifname_log_txt =', ifname_log_txt
    print 'ofname_hosts_txt =', ofname_hosts_txt
    print 'ofname_hours_txt =', ofname_hours_txt
    print 'ofname_resources_txt =', ofname_resources_txt
    print 'ofname_blocked_txt =', ofname_blocked_txt
    print
    
    logAnalysis = LogAnalysis(ofname_hosts_txt, ofname_hours_txt, ofname_resources_txt, ofname_blocked_txt)
    
    logAnalysis.process_file(ifname_log_txt)

